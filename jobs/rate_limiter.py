import time
import uuid
from math import ceil

from django.conf import settings

from jobs.pending_queue import get_redis_client


RATE_LIMIT_KEY = "jobs:email:rate-limit"


def get_rate_limit():
    """
    Return the configured global email rate limit.

    Example:
        EMAIL_RATE_LIMIT = 4
        EMAIL_RATE_WINDOW_SECONDS = 60

    Means:
        Maximum 4 emails per 60-second rolling window.
    """

    limit = getattr(
        settings,
        "EMAIL_RATE_LIMIT",
        200,
    )

    window_seconds = getattr(
        settings,
        "EMAIL_RATE_WINDOW_SECONDS",
        60,
    )

    if limit < 1:
        raise ValueError(
            "EMAIL_RATE_LIMIT must be at least 1."
        )

    if window_seconds <= 0:
        raise ValueError(
            "EMAIL_RATE_WINDOW_SECONDS must be greater than 0."
        )

    return limit, window_seconds


def get_rate_limit_status():
    """
    Return a human-readable snapshot of the current rolling window.

    Inspecting the status also removes expired reservations.  It never adds a
    reservation, so the command is safe to run repeatedly while a dispatcher
    is active.
    """
    client = get_redis_client()
    limit, window_seconds = get_rate_limit()
    now = time.time()
    window_start = now - window_seconds

    client.zremrangebyscore(
        RATE_LIMIT_KEY,
        "-inf",
        window_start,
    )

    used = int(client.zcard(RATE_LIMIT_KEY))
    remaining = max(limit - used, 0)
    retry_after = 0

    if used >= limit:
        oldest = client.zrange(
            RATE_LIMIT_KEY,
            0,
            0,
            withscores=True,
        )

        if oldest:
            retry_after = max(
                ceil(
                    window_seconds
                    - (now - float(oldest[0][1]))
                ),
                0,
            )

    return {
        "limit": limit,
        "window_seconds": window_seconds,
        "used": used,
        "remaining": remaining,
        "retry_after": retry_after,
    }


def acquire_rate_limit_slot():
    """
    Atomically check and consume one global rate-limit slot.

    Uses a Redis sorted set:

        score  = timestamp
        member = unique UUID

    The Lua script performs atomically:

        1. Remove expired entries.
        2. Count currently consumed slots.
        3. If full, calculate retry-after.
        4. Otherwise consume one new slot.

    Returns:
        (True, 0)
            A slot was acquired.

        (False, retry_after_seconds)
            No capacity is currently available.
    """

    client = get_redis_client()

    limit, window_seconds = get_rate_limit()

    now = time.time()

    member = str(uuid.uuid4())

    lua_script = """
    local key = KEYS[1]

    local now = tonumber(ARGV[1])
    local window = tonumber(ARGV[2])
    local limit = tonumber(ARGV[3])
    local member = ARGV[4]

    local window_start = now - window

    redis.call(
        "ZREMRANGEBYSCORE",
        key,
        "-inf",
        window_start
    )

    local current_count = redis.call(
        "ZCARD",
        key
    )

    if current_count >= limit then

        local oldest = redis.call(
            "ZRANGE",
            key,
            0,
            0,
            "WITHSCORES"
        )

        local retry_after = window

        if oldest[2] then
            retry_after =
                window - (now - tonumber(oldest[2]))
        end

        return {
            0,
            math.ceil(retry_after)
        }
    end

    redis.call(
        "ZADD",
        key,
        now,
        member
    )

    redis.call(
        "EXPIRE",
        key,
        math.ceil(window) + 1
    )

    return {
        1,
        0
    }
    """

    result = client.eval(
        lua_script,
        1,
        RATE_LIMIT_KEY,
        now,
        window_seconds,
        limit,
        member,
    )

    allowed = bool(result[0])
    retry_after = int(result[1])

    return allowed, retry_after
