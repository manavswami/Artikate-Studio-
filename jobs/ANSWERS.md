# Section 2 — Worker SIGKILL Behaviour

The Celery task is configured with `acks_late=True` and
`reject_on_worker_lost=True`.

By default, acknowledgement timing is critical to crash behaviour. With late
acknowledgement, the task is acknowledged only after execution rather than
before execution. If the worker process is SIGKILL'd while processing an email,
the broker message remains unacknowledged and can be redelivered.

`reject_on_worker_lost=True` causes Celery to reject and requeue the task when
the worker child process exits unexpectedly.

Therefore, the implementation provides at-least-once delivery semantics.

This prevents silent job loss, but it introduces a duplicate-execution risk.
For example, the following sequence is possible:

1. Celery worker sends the email.
2. The provider accepts it.
3. The worker is SIGKILL'd before acknowledging the Celery task.
4. The broker redelivers the unacknowledged task.
5. The email may be sent again.

Therefore, `acks_late=True` alone does not provide exactly-once delivery.
A production system should use an idempotency key based on the stable `job_id`,
either through provider-supported idempotency or a durable database record that
tracks completed deliveries.

This is a deliberate trade-off: at-least-once delivery avoids silent job loss,
while idempotency is required to control duplicate side effects.