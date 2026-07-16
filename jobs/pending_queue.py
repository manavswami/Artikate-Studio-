import json
import time
import uuid

import redis
from django.conf import settings


# ============================================================
# Redis keys
# ============================================================

PENDING_EMAIL_QUEUE_KEY = "jobs:email:pending"
PROCESSING_EMAIL_QUEUE_KEY = "jobs:email:processing"
DEAD_LETTER_EMAIL_QUEUE_KEY = "jobs:email:dead-letter"

# Recording and test evidence. These counters live next to the queue state so
# the jobs app has one Redis storage module instead of separate metrics files.
COMPLETED_JOBS_KEY = "jobs:email:completed"
RETRY_COUNTS_KEY = "jobs:email:retry-counts"
DISPATCH_TIMESTAMPS_KEY = "jobs:email:dispatch-timestamps"
SUBMITTED_METRIC_KEY = "jobs:metrics:submitted"
DISPATCHED_METRIC_KEY = "jobs:metrics:dispatched"
COMPLETED_METRIC_KEY = "jobs:metrics:completed"
FAILED_METRIC_KEY = "jobs:metrics:failed"
RETRY_METRIC_KEY = "jobs:metrics:retry"
START_TIME_METRIC_KEY = "jobs:metrics:start-time"

# Prevents multiple dispatcher chains from processing the
# same global pending queue simultaneously.
DISPATCHER_LOCK_KEY = "jobs:email:dispatcher-lock"

# Default safety TTL. The lock is refreshed before a scheduled
# dispatcher retry when a longer wait is necessary.
DISPATCHER_LOCK_TTL_SECONDS = 300


def get_redis_client():
    """
    Return the Redis client used by our custom email queue.

    EMAIL_QUEUE_REDIS_URL may point to a dedicated Redis DB.
    If it is not configured, the Celery broker URL is used.
    """

    redis_url = getattr(
        settings,
        "EMAIL_QUEUE_REDIS_URL",
        settings.CELERY_BROKER_URL,
    )

    return redis.Redis.from_url(
        redis_url,
        decode_responses=True,
    )


# ============================================================
# Dispatcher lock
# ============================================================

def acquire_dispatcher_lock():
    """
    Atomically acquire the global dispatcher lock.

    Redis SET NX guarantees that only one caller can acquire
    the lock, even if several processes attempt it concurrently.

    Returns:
        Unique ownership token if acquired.
        None if another dispatcher already owns the lock.
    """

    client = get_redis_client()

    lock_token = str(uuid.uuid4())

    acquired = client.set(
        DISPATCHER_LOCK_KEY,
        lock_token,
        nx=True,
        ex=DISPATCHER_LOCK_TTL_SECONDS,
    )

    if acquired:
        return lock_token

    return None


def refresh_dispatcher_lock(
    lock_token,
    *,
    ttl_seconds=DISPATCHER_LOCK_TTL_SECONDS,
):
    """
    Extend the lock TTL only if the supplied token still owns it.

    The comparison and EXPIRE happen atomically using Lua.
    """

    if not lock_token:
        return False

    client = get_redis_client()

    lua_script = """
    if redis.call("GET", KEYS[1]) == ARGV[1] then
        return redis.call("EXPIRE", KEYS[1], ARGV[2])
    end

    return 0
    """

    result = client.eval(
        lua_script,
        1,
        DISPATCHER_LOCK_KEY,
        lock_token,
        int(ttl_seconds),
    )

    return bool(result)


def release_dispatcher_lock(lock_token):
    """
    Release the dispatcher lock only if we still own it.

    We must not simply DELETE the key because an expired lock
    could already have been acquired by another dispatcher.
    """

    if not lock_token:
        return False

    client = get_redis_client()

    lua_script = """
    if redis.call("GET", KEYS[1]) == ARGV[1] then
        return redis.call("DEL", KEYS[1])
    end

    return 0
    """

    result = client.eval(
        lua_script,
        1,
        DISPATCHER_LOCK_KEY,
        lock_token,
    )

    return bool(result)


def dispatcher_is_locked():
    """
    Return True when one dispatcher chain is already active
    or waiting for its next scheduled retry.
    """

    return bool(
        get_redis_client().exists(
            DISPATCHER_LOCK_KEY
        )
    )


# ============================================================
# Add jobs
# ============================================================

def enqueue_email(
    *,
    email,
    subject,
    message,
    job_id=None,
    fail_once=False,
    always_fail=False,
):
    """
    Add exactly one email job to the Redis pending queue.

    Important:
        This function does not create a Celery email task.

        The job remains dormant in Redis until the dispatcher
        determines that rate-limit capacity is available.
    """

    client = get_redis_client()

    # Always create a unique ID when one is not explicitly supplied.
    if job_id is None:
        job_id = str(uuid.uuid4())

    payload = {
        "job_id": job_id,
        "email": email,
        "subject": subject,
        "message": message,
        "fail_once": fail_once,
        "always_fail": always_fail,
    }

    raw_job = json.dumps(payload)

    client.rpush(
        PENDING_EMAIL_QUEUE_KEY,
        raw_job,
    )

    return payload


# ============================================================
# Atomic queue transitions
# ============================================================

def move_next_job_to_processing():
    """
    Atomically move one job:

        pending -> processing

    Lua is used because:

        LPOP pending
        RPUSH processing

    as two separate operations could lose a job if the process
    crashes between the two commands.
    """

    client = get_redis_client()

    lua_script = """
    local job = redis.call("LPOP", KEYS[1])

    if not job then
        return nil
    end

    redis.call("RPUSH", KEYS[2], job)

    return job
    """

    return client.eval(
        lua_script,
        2,
        PENDING_EMAIL_QUEUE_KEY,
        PROCESSING_EMAIL_QUEUE_KEY,
    )


def remove_from_processing(raw_job):
    """
    Remove one successfully completed email job from processing.
    """

    return get_redis_client().lrem(
        PROCESSING_EMAIL_QUEUE_KEY,
        1,
        raw_job,
    )


def move_processing_to_dead_letter(raw_job):
    """
    Atomically move a permanently failed job:

        processing -> dead-letter
    """

    client = get_redis_client()

    lua_script = """
    local removed = redis.call(
        "LREM",
        KEYS[1],
        1,
        ARGV[1]
    )

    if removed > 0 then
        redis.call(
            "RPUSH",
            KEYS[2],
            ARGV[1]
        )
    end

    return removed
    """

    return client.eval(
        lua_script,
        2,
        PROCESSING_EMAIL_QUEUE_KEY,
        DEAD_LETTER_EMAIL_QUEUE_KEY,
        raw_job,
    )


# ============================================================
# Queue inspection
# ============================================================

def get_pending_count():
    return get_redis_client().llen(
        PENDING_EMAIL_QUEUE_KEY
    )


def get_processing_count():
    return get_redis_client().llen(
        PROCESSING_EMAIL_QUEUE_KEY
    )


def get_dead_letter_count():
    return get_redis_client().llen(
        DEAD_LETTER_EMAIL_QUEUE_KEY
    )


# ============================================================
# Recording metrics and rate-limit audit
# ============================================================

def start_queue_run():
    get_redis_client().set(
        START_TIME_METRIC_KEY,
        time.time(),
    )


def record_submitted(count=1):
    return get_redis_client().incrby(
        SUBMITTED_METRIC_KEY,
        count,
    )


def record_dispatched(job_id):
    """Record one pending -> processing transition and its reservation time."""
    client = get_redis_client()
    timestamp = time.time()

    # A job ID is unique within a queue run, so it is a readable audit member.
    client.zadd(
        DISPATCH_TIMESTAMPS_KEY,
        {job_id: timestamp},
    )
    return client.incr(DISPATCHED_METRIC_KEY)


def record_completed(job_id):
    client = get_redis_client()
    client.sadd(COMPLETED_JOBS_KEY, job_id)
    return client.incr(COMPLETED_METRIC_KEY)


def record_retry(job_id):
    client = get_redis_client()
    retry_count = client.hincrby(
        RETRY_COUNTS_KEY,
        job_id,
        1,
    )
    client.incr(RETRY_METRIC_KEY)
    return retry_count


def record_failed():
    return get_redis_client().incr(
        FAILED_METRIC_KEY
    )


def _metric_value(key):
    value = get_redis_client().get(key)
    return int(value or 0)


def get_completed_job_ids():
    values = get_redis_client().smembers(
        COMPLETED_JOBS_KEY
    )
    return {
        value.decode()
        if isinstance(value, bytes)
        else value
        for value in values
    }


def get_retry_count(job_id):
    value = get_redis_client().hget(
        RETRY_COUNTS_KEY,
        job_id,
    )
    return int(value or 0)


def get_max_dispatches_in_rolling_window(window_seconds):
    records = get_redis_client().zrange(
        DISPATCH_TIMESTAMPS_KEY,
        0,
        -1,
        withscores=True,
    )
    timestamps = sorted(
        float(timestamp)
        for _, timestamp in records
    )

    maximum = 0
    left = 0

    for right, timestamp in enumerate(timestamps):
        while timestamp - timestamps[left] >= window_seconds:
            left += 1
        maximum = max(maximum, right - left + 1)

    return maximum


def get_queue_metrics():
    started_at = get_redis_client().get(
        START_TIME_METRIC_KEY
    )
    elapsed = (
        max(int(time.time() - float(started_at)), 0)
        if started_at is not None
        else 0
    )
    completed = _metric_value(COMPLETED_METRIC_KEY)

    return {
        "submitted": _metric_value(SUBMITTED_METRIC_KEY),
        "dispatched": _metric_value(DISPATCHED_METRIC_KEY),
        "completed": completed,
        "retries": _metric_value(RETRY_METRIC_KEY),
        "failed": _metric_value(FAILED_METRIC_KEY),
        "elapsed": elapsed,
        "throughput": (
            round(completed / elapsed, 2)
            if elapsed
            else 0
        ),
    }


def clear_queue_metrics():
    get_redis_client().delete(
        COMPLETED_JOBS_KEY,
        RETRY_COUNTS_KEY,
        DISPATCH_TIMESTAMPS_KEY,
        SUBMITTED_METRIC_KEY,
        DISPATCHED_METRIC_KEY,
        COMPLETED_METRIC_KEY,
        FAILED_METRIC_KEY,
        RETRY_METRIC_KEY,
        START_TIME_METRIC_KEY,
    )
