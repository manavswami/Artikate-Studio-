import json
import logging

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from django.conf import settings
from django.core.mail import send_mail

from jobs.pending_queue import (
    acquire_dispatcher_lock,
    get_pending_count,
    move_next_job_to_processing,
    move_processing_to_dead_letter,
    record_completed,
    record_dispatched,
    record_failed,
    record_retry,
    refresh_dispatcher_lock,
    release_dispatcher_lock,
    remove_from_processing,
)
from jobs.rate_limiter import acquire_rate_limit_slot


logger = logging.getLogger(__name__)


# ============================================================
# Configuration
# ============================================================

BASE_RETRY_DELAY_SECONDS = 5
MAX_EMAIL_RETRIES = 3


# ============================================================
# Individual Email Task
# ============================================================

@shared_task(
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=MAX_EMAIL_RETRIES,
)
def send_transactional_email(
    self,
    *,
    job_id,
    email,
    subject,
    message,
    processing_payload,
    fail_once=False,
    always_fail=False,
):
    """
    Send one transactional email.

    Features:

        - One email = one Celery task.
        - Late acknowledgement.
        - Exponential backoff.
        - Maximum retry limit.
        - Dead-letter queue after permanent failure.
        - Processing queue cleanup after success.
        - Detailed runtime logging.

    Backoff schedule:

        Initial failure -> retry after 5 seconds.
        Retry 1 failure -> retry after 10 seconds.
        Retry 2 failure -> retry after 20 seconds.
        Retry 3 failure -> dead-letter queue.
    """

    current_retry = self.request.retries
    task_id = self.request.id

    try:
        # ----------------------------------------------------
        # Testing hooks
        # ----------------------------------------------------

        if always_fail:
            raise RuntimeError(
                "Simulated permanent email provider failure."
            )

        if fail_once and current_retry == 0:
            raise RuntimeError(
                "Simulated temporary email provider failure."
            )

        # ----------------------------------------------------
        # Send email
        # ----------------------------------------------------

        send_mail(
            subject=subject,
            message=message,
            from_email=None,
            recipient_list=[email],
            fail_silently=False,
        )

        # ----------------------------------------------------
        # Success: remove from processing queue
        # ----------------------------------------------------

        removed_from_processing = remove_from_processing(
            processing_payload
        )

        record_completed(job_id)

        # Normal one-attempt successes would create hundreds of repetitive
        # lines in a 250-job recording. The monitor proves their count; the
        # worker log focuses on the recovery path worth explaining.
        if current_retry:
            logger.info(
                "[RETRY_RECOVERED] job=%s task=%s attempt=%s/%s "
                "processing_removed=%s",
                job_id,
                task_id,
                current_retry + 1,
                self.max_retries + 1,
                removed_from_processing,
            )

        return {
            "status": "sent",
            "job_id": job_id,
            "task_id": task_id,
            "recipient": email,
            "attempt": current_retry + 1,
        }

    except Exception as exc:
        # ----------------------------------------------------
        # Permanent failure
        # ----------------------------------------------------

        if current_retry >= self.max_retries:
            move_processing_to_dead_letter(
                processing_payload
            )
            record_failed()

            logger.error(
                "[DEAD_LETTER] job=%s task=%s attempts=%s "
                "action=moved_to_dead_letter error=%s",
                job_id,
                task_id,
                current_retry + 1,
                exc,
            )

            return {
                "status": "dead-lettered",
                "job_id": job_id,
                "task_id": task_id,
                "recipient": email,
                "attempts": current_retry + 1,
                "error": str(exc),
            }

        # ----------------------------------------------------
        # Exponential backoff
        # ----------------------------------------------------

        retry_delay = (
            BASE_RETRY_DELAY_SECONDS
            * (2 ** current_retry)
        )

        recorded_retries = record_retry(job_id)

        logger.warning(
            "[RETRY_SCHEDULED] job=%s task=%s failed_attempt=%s/%s "
            "backoff=%ss formula=%s*(2**%s) retry_events=%s error=%s",
            job_id,
            task_id,
            current_retry + 1,
            self.max_retries + 1,
            retry_delay,
            BASE_RETRY_DELAY_SECONDS,
            current_retry,
            recorded_retries,
            exc,
        )

        try:
            raise self.retry(
                exc=exc,
                countdown=retry_delay,
            )

        except MaxRetriesExceededError:
            move_processing_to_dead_letter(
                processing_payload
            )
            record_failed()

            logger.error(
                "[DEAD_LETTER] job=%s task=%s action=max_retries_exceeded",
                job_id,
                task_id,
            )

            return {
                "status": "dead-lettered",
                "job_id": job_id,
                "task_id": task_id,
                "recipient": email,
            }


# ============================================================
# Dispatcher Task
# ============================================================

@shared_task(
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=None,
)
def dispatch_pending_emails(
    self,
    lock_token=None,
):
    """
    Dispatch pending emails according to global Redis rate limit.

    Important architecture:

        Redis pending queue
                |
                v
          Dispatcher task
                |
                | Only when rate-limit capacity exists
                v
        Individual Celery email task

    Example:

        Pending emails: 100
        Rate limit:     4 per 60 seconds

    Result:

        First dispatcher execution:
            4 individual Celery email tasks created.
            96 emails remain dormant in Redis.

        When capacity becomes available:
            Dispatcher retries itself.
            Next allowed emails are dispatched.

    This avoids creating 100 Celery tasks when only 4 can actually
    be processed in the current rate-limit window.
    """

    rate_limit = getattr(
        settings,
        "EMAIL_RATE_LIMIT",
        200,
    )

    window_seconds = getattr(
        settings,
        "EMAIL_RATE_WINDOW_SECONDS",
        60,
    )

    # Tracks emails dispatched during this specific execution.
    dispatched_count = 0

    # --------------------------------------------------------
    # Acquire or continue dispatcher lock
    # --------------------------------------------------------

    if lock_token is None:
        lock_token = acquire_dispatcher_lock()

        if lock_token is None:
            logger.info(
                "[DISPATCHER_SKIPPED] reason=lock_already_held"
            )

            return {
                "status": "already-running",
                "dispatched": 0,
                "pending": get_pending_count(),
            }

    else:
        # This dispatcher was retried after hitting the rate limit.
        lock_refreshed = refresh_dispatcher_lock(
            lock_token
        )

        if not lock_refreshed:
            logger.warning(
                "[DISPATCHER_STOPPED] reason=lock_lost"
            )

            return {
                "status": "lock-lost",
                "dispatched": 0,
                "pending": get_pending_count(),
            }

    initial_pending = get_pending_count()

    logger.info(
        "[DISPATCHER_STARTED] task=%s pending=%s rate_limit=%s/%ss",
        self.request.id,
        initial_pending,
        rate_limit,
        window_seconds,
    )

    try:
        while get_pending_count() > 0:

            # ------------------------------------------------
            # Try to reserve one global rate-limit slot
            # ------------------------------------------------

            allowed, retry_after = (
                acquire_rate_limit_slot()
            )

            if not allowed:
                pending_count = get_pending_count()

                logger.warning(
                    "[RATE_LIMIT_REACHED] rate=%s/%ss dispatched=%s "
                    "pending=%s retry_in=%ss action=jobs_stay_in_redis",
                    rate_limit,
                    window_seconds,
                    dispatched_count,
                    pending_count,
                    retry_after,
                )

                # Keep the lock alive while this same dispatcher
                # waits for the next rate-limit window.
                refresh_dispatcher_lock(
                    lock_token
                )

                raise self.retry(
                    countdown=max(
                        int(retry_after),
                        1,
                    ),
                    kwargs={
                        "lock_token": lock_token,
                    },
                )

            # ------------------------------------------------
            # Move one job atomically:
            #
            # pending -> processing
            # ------------------------------------------------

            raw_job = move_next_job_to_processing()

            if raw_job is None:
                break

            try:
                job = json.loads(raw_job)

            except (
                json.JSONDecodeError,
                TypeError,
            ) as exc:
                logger.exception(
                    "\n"
                    "[INVALID QUEUE PAYLOAD]\n"
                    "Raw payload : %s\n"
                    "Error       : %s",
                    raw_job,
                    exc,
                )

                move_processing_to_dead_letter(
                    raw_job
                )

                continue

            # ------------------------------------------------
            # Create one individual email Celery task
            # ------------------------------------------------

            send_transactional_email.delay(
                job_id=job["job_id"],
                email=job["email"],
                subject=job["subject"],
                message=job["message"],
                processing_payload=raw_job,
                fail_once=job.get(
                    "fail_once",
                    False,
                ),
                always_fail=job.get(
                    "always_fail",
                    False,
                ),
            )

            dispatched_count += 1
            record_dispatched(job["job_id"])

            current_pending = get_pending_count()

            if dispatched_count == 1 or dispatched_count % 25 == 0:
                logger.info(
                    "[DISPATCH_PROGRESS] task=%s dispatched=%s "
                    "pending=%s last_job=%s",
                    self.request.id,
                    dispatched_count,
                    current_pending,
                    job["job_id"],
                )

        # ----------------------------------------------------
        # Queue is empty
        # ----------------------------------------------------

        final_pending = get_pending_count()

        logger.info(
            "[DISPATCHER_COMPLETE] task=%s started_pending=%s "
            "dispatched=%s pending=%s",
            self.request.id,
            initial_pending,
            dispatched_count,
            final_pending,
        )

        release_dispatcher_lock(
            lock_token
        )

        return {
            "status": "complete",
            "rate_limit": rate_limit,
            "window_seconds": window_seconds,
            "initial_pending": initial_pending,
            "dispatched": dispatched_count,
            "pending": final_pending,
        }

    except Exception as exc:
        # Celery Retry is intentionally raised by self.retry().
        # It must not be treated as a real dispatcher crash.
        from celery.exceptions import Retry

        if isinstance(exc, Retry):
            raise

        logger.exception(
            "[DISPATCHER_CRASHED] task=%s dispatched=%s pending=%s error=%s",
            self.request.id,
            dispatched_count,
            get_pending_count(),
            exc,
        )

        # Release the lock after a genuine unexpected failure.
        release_dispatcher_lock(
            lock_token
        )

        raise
