# Job Queue System Design

## 1. Overview
## Demo link  https://drive.google.com/file/d/1P3VQPw-j8rHlVHh-9FF8Bui7TpQtRp99/view?usp=sharing



This project implements a reliable background job queue for sending transactional emails.

The system uses:

- Celery for background task execution.
- Redis as the Celery broker and result backend.
- Redis lists for pending, processing, and dead-letter queues.
- A Redis sorted set for global sliding-window rate limiting.
- Redis Lua scripts for atomic operations.
- Exponential backoff for temporary failures.
- Dead-letter handling for permanently failed jobs.
- Late acknowledgement for better recovery from worker crashes.

The main goals are:

1. Process jobs asynchronously.
2. Never exceed the configured global rate limit.
3. Avoid creating unnecessary Celery tasks when the rate limit is already full.
4. Retry temporary failures with exponential backoff.
5. Preserve permanently failed jobs in a dead-letter queue.
6. Reduce the chance of losing jobs when a worker crashes.


---

## 2. Architecture Choice

Three approaches were considered:

### Option 1: Celery + Redis

Advantages:

- Mature and widely used.
- Supports distributed workers.
- Built-in retry support.
- Supports delayed task execution using countdown.
- Works well with Django.
- Redis can be used for both messaging and rate limiting.

Disadvantages:

- Requires running Celery workers and Redis.
- More operational complexity than an in-process queue.
- Delivery is generally at-least-once, so duplicate execution is possible.

### Option 2: Django Q

Advantages:

- Good Django integration.
- Simpler for small Django applications.
- Supports background tasks and scheduling.

Disadvantages:

- Smaller ecosystem than Celery.
- Less common for large distributed task-processing systems.
- Celery provides more mature retry and worker-management features.

### Option 3: Custom Queue Implementation

Advantages:

- Full control over queue behaviour.
- Can be designed specifically for the application.

Disadvantages:

- Difficult to implement correctly.
- Requires custom retry, worker management, crash recovery, scheduling, and monitoring.
- Higher maintenance cost.
- Greater risk of reliability bugs.

### Final Choice

I chose **Celery + Redis**.

Celery provides mature background task execution, retries, delayed execution, and worker management. Redis is also used for queue state and global rate limiting.

This provides a good balance between reliability, scalability, implementation complexity, and maintainability.


---

## 3. High-Level Architecture

The job flow is:

    Application
        |
        v
    Redis Pending Queue
        |
        v
    Dispatcher Task
        |
        | Checks global Redis rate limiter
        |
        v
    Redis Processing Queue
        |
        v
    Individual Celery Email Task
        |
        +-------------------+
        |                   |
        v                   v
      Success            Failure
        |                   |
        v                   v
    Remove from        Exponential Backoff
    Processing          5s -> 10s -> 20s
                            |
                            v
                    Maximum retries reached
                            |
                            v
                    Dead-Letter Queue

Jobs first enter the Redis pending queue.

The dispatcher checks whether rate-limit capacity is available. Only then does it move a job from pending to processing and create an individual Celery email task.

This means that if 500 jobs are waiting but only 4 jobs are allowed in the current rate-limit window, only the allowed jobs become Celery email tasks. The remaining jobs stay in Redis instead of creating hundreds of unnecessary Celery retry tasks.


---

## 4. Queue Design

The implementation uses three main Redis queues:

### Pending Queue

Contains jobs waiting for rate-limit capacity.

### Processing Queue

Contains jobs that have been accepted for processing.

A job is moved atomically from pending to processing before its individual Celery task is created.

### Dead-Letter Queue

Contains permanently failed jobs.

A job is moved to this queue after the maximum retry count is reached. This prevents failed jobs from disappearing and allows later investigation or manual reprocessing.


---

## 5. Retry and Exponential Backoff

Temporary email failures are retried using exponential backoff.

The formula is:

    delay = base_delay * (2 ** current_retry)

With a base delay of 5 seconds:

    Initial attempt fails -> retry after 5 seconds
    Retry 1 fails         -> retry after 10 seconds
    Retry 2 fails         -> retry after 20 seconds
    Final failure         -> move to dead-letter queue

No `time.sleep()` is used.

Celery schedules the retry using:

    self.retry(countdown=retry_delay)

This does not block the worker while waiting for the retry time.


---

## 6. Rate Limiter Choice

The implementation uses a **Redis sliding-window rate limiter**.

Redis stores successful rate-limit reservations in a sorted set. The timestamp is used as the sorted-set score.

For each request, the rate limiter:

1. Removes timestamps older than the current time window.
2. Counts the remaining timestamps.
3. If the count is below the configured limit, adds the new reservation.
4. Otherwise, rejects the request and calculates when capacity will next become available.

The main Redis operations are conceptually:

    ZREMRANGEBYSCORE
    ZCARD
    ZADD
    EXPIRE

These operations are executed together inside one Redis Lua script.


---

## 7. Why Sliding Window?

Three approaches were considered.

### Token Bucket

Advantages:

- Supports controlled bursts.
- Good for systems that need average throughput limits.

Disadvantages:

- More complex token-refill logic.
- Allows bursts by design.

### Fixed Window

Advantages:

- Very simple.
- Easy to implement with `INCR` and `EXPIRE`.

Disadvantages:

- Can allow large bursts around window boundaries.

For example, with a limit of 4 emails per minute:

    12:00:59 -> 4 emails
    12:01:00 -> 4 emails

Eight emails could therefore be sent within approximately one second.

### Sliding Window

Advantages:

- Enforces the limit over a true rolling time period.
- Prevents fixed-window boundary bursts.
- Easy to reason about and test.

Disadvantages:

- Uses more Redis memory because timestamps are stored.
- Slightly more complex than a fixed-window counter.

### Final Choice

I chose the **sliding-window approach** because the requirement is to guarantee that the global rate limit is never exceeded during any rolling time window.


---

## 8. Atomicity

The rate limiter must work correctly even when multiple workers run concurrently.

A non-atomic implementation would be unsafe:

    Worker A reads count = 3
    Worker B reads count = 3

    Limit = 4

    Worker A allows a job
    Worker B also allows a job

The result would be 5 jobs in a window with a limit of 4.

To prevent this, the complete rate-limit decision is performed inside a single Redis Lua script.

Redis executes the Lua script atomically, so another command cannot modify the rate-limit state in the middle of the operation.

Atomic Redis operations are also used for important queue transitions, such as moving a job from:

    pending -> processing

and:

    processing -> dead-letter

This prevents partial queue-state changes.


---

## 9. Redis Failure Behaviour

The system uses a **fail-closed** strategy.

If Redis is unavailable, the application cannot safely verify the global rate limit. Therefore, it does not send the email without acquiring a valid rate-limit slot.

The behaviour is:

    Redis available
        -> Check rate limit
        -> Dispatch if allowed

    Redis unavailable
        -> Cannot safely verify capacity
        -> Do not dispatch
        -> Retry later

This protects the external email provider from receiving more requests than allowed.

The trade-off is reduced availability during a Redis outage, but for this system correctness and rate-limit protection are more important than sending immediately.


---

## 10. Bounded Dispatching

A major architecture decision is that all pending jobs are not immediately submitted as individual Celery tasks.

For example:

    Pending jobs: 100
    Rate limit:   1 email per minute

A naive implementation could create 100 Celery tasks immediately. One task would run and the others would repeatedly retry because the rate limit is full.

That creates unnecessary broker traffic, worker activity, and retry load.

This implementation instead keeps jobs in the Redis pending queue.

The dispatcher only creates individual Celery email tasks when rate-limit capacity is available.

Therefore:

    100 pending jobs
    1 available rate-limit slot

Result:

    1 individual Celery email task created
    99 jobs remain pending in Redis

This reduces unnecessary load.


---

## 11. Dispatcher Lock

A Redis-based dispatcher lock ensures that only one dispatcher chain actively drains the pending queue at a time.

Without this lock, multiple dispatchers could process the same logical queue concurrently and create unnecessary contention.

The lock is acquired using Redis atomic operations with unique ownership tokens.

The lock is released only by its owner.

When the dispatcher reaches the global rate limit, it schedules itself for later using Celery retry with a countdown instead of blocking a worker with `time.sleep()`.


---

## 12. What Happens if a Celery Worker Is SIGKILL'd?

The individual email task is configured with:

    acks_late=True
    reject_on_worker_lost=True

### `acks_late=True`

Normally, a task can be acknowledged before execution.

With late acknowledgement, Celery acknowledges the task after successful task execution.

If the worker dies before completion, the task has not been successfully acknowledged.

### `reject_on_worker_lost=True`

This tells Celery to reject or requeue the task when the worker process executing it is unexpectedly lost.

Therefore, if a worker is killed while processing a task, the task can be delivered again instead of being silently treated as successfully completed.

This improves reliability, but it creates **at-least-once delivery**, not exactly-once delivery.


---

## 13. Duplicate Execution Risk

Consider this sequence:

    1. Worker receives email task.
    2. Email provider successfully sends the email.
    3. Worker is SIGKILL'd before Celery receives the final acknowledgement.
    4. The task is delivered again.
    5. The email could be sent twice.

Therefore, `acks_late=True` prevents many forms of job loss but cannot guarantee exactly-once execution.

For a production system, the job ID should be used as an idempotency key.

Ideally:

    1. Every job has a unique job_id.
    2. The system records completed job IDs.
    3. Before sending, the task checks whether the job was already completed.
    4. If the email provider supports idempotency keys, job_id should also be sent to the provider.

This reduces duplicate side effects during worker crashes and task redelivery.


---

## 14. Celery Configuration

Important Celery configuration includes:

    task_acks_late = True
    task_reject_on_worker_lost = True

The task itself also explicitly uses:

    acks_late=True
    reject_on_worker_lost=True

These settings help recover unacknowledged tasks after unexpected worker termination.

Redis broker visibility timeout should also be configured appropriately. An unacknowledged task may become available for redelivery after the visibility timeout.


---

## 15. Testing Strategy

The system includes tests for:

- Pending queue behaviour.
- Atomic queue movement.
- Sliding-window rate limiting.
- Redis Lua atomicity.
- Dispatcher locking.
- Bounded task dispatching.
- Successful email processing.
- Exponential backoff.
- Maximum retry handling.
- Dead-letter queue behaviour.

The required 500-job test should submit exactly 500 jobs and verify:

1. No job is lost.
2. The configured rate limit is never exceeded.
3. At least one intentional temporary failure is retried correctly.

The intentional failure should fail once and then succeed on retry.

A useful invariant is:

    pending
    + processing
    + completed
    + dead-lettered
    = total submitted jobs

For 500 submitted jobs:

    pending
    + processing
    + completed
    + dead-lettered
    = 500

This provides a clear way to verify that no job disappeared.


---

## 16. Trade-offs and Limitations

The current architecture provides:

- Distributed background processing.
- Atomic global rate limiting.
- Exponential backoff.
- Dead-letter handling.
- Protection against unnecessary Celery task creation.
- Improved worker-crash recovery.

The main trade-offs are:

- Redis is a critical dependency.
- Fail-closed behaviour reduces availability during Redis outages.
- Sliding-window rate limiting uses more memory than fixed-window counters.
- At-least-once delivery means duplicate execution is possible.
- Exactly-once email sending requires stronger idempotency support.


---

## 17. Final Summary

The chosen architecture is:

    Django
        +
    Celery
        +
    Redis broker/backend
        +
    Redis pending/processing/dead-letter queues
        +
    Atomic Lua-based sliding-window rate limiter

The main design decisions are:

- Celery + Redis was chosen over Django Q and a fully custom worker system because it provides mature distributed task execution and retry support.
- Sliding-window rate limiting was chosen because it provides a stronger rolling-window guarantee than fixed-window limiting.
- Lua scripts guarantee atomic Redis operations.
- Redis failures fail closed to protect the global rate limit.
- Exponential backoff uses Celery countdown and never `time.sleep()`.
- Permanent failures are moved to a dead-letter queue.
- `acks_late=True` and `reject_on_worker_lost=True` improve recovery when a Celery worker is unexpectedly killed.
- Jobs remain pending in Redis until rate-limit capacity exists, preventing unnecessary Celery task creation.

This architecture is designed for correctness, reliability, and clear operational behaviour while keeping the implementation reasonably simple.


---

## 18. Live Observability and Recording Evidence

The live demonstration uses Redis-backed operational counters in addition to
the three queue lists. This makes the behaviour verifiable while the system is
running rather than relying on a narrator to infer it from Celery output.

`python manage.py queue_status --watch --interval 1` reports:

- Pending, processing, and dead-letter queue lengths.
- Whether the dispatcher lock is active.
- Submitted, dispatched, completed, retried, and permanently failed job
  counts.
- Current sliding-window occupancy, remaining capacity, and seconds until the
  next permit when the limiter is full.
- The maximum number of dispatch reservations observed in any rolling rate
  window during the run.

The final value is calculated from a separate dispatch audit sorted set. Unlike
the live limiter key, this audit is not expired during the demo. It therefore
answers the important retrospective question directly:

    Did any rolling 60-second window exceed 200 dispatches?

For a correct run, the monitor displays:

    Rate audit  max rolling window=200/200 -> PASS

The `queue_demo` command creates a recording-ready run with 250 jobs and one
intentional `fail_once` job. More than 200 jobs are necessary: a 100-job batch
can show queue movement but cannot fill a 200-per-minute window and therefore
cannot prove the throttle is active. The temporary failure happens before the
console email backend sends a message, then the task logs its job ID, attempt,
error, retry delay, and backoff formula before Celery schedules the retry.
