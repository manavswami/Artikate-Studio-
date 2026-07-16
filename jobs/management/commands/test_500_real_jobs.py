import json
import time
import uuid

from django.conf import settings
from django.core.management.base import (
    BaseCommand,
    CommandError,
)

from jobs.pending_queue import (
    DISPATCHER_LOCK_KEY,
    clear_queue_metrics,
    get_completed_job_ids,
    get_max_dispatches_in_rolling_window,
    get_pending_count,
    get_redis_client,
    get_retry_count,
    record_submitted,
    start_queue_run,
)
from jobs.rate_limiter import RATE_LIMIT_KEY
from jobs.tasks import dispatch_pending_emails


TOTAL_JOBS = 500

PENDING_QUEUE_KEY = "jobs:email:pending"
PROCESSING_QUEUE_KEY = "jobs:email:processing"
DEAD_LETTER_QUEUE_KEY = "jobs:email:dead-letter"

INTENTIONAL_FAILURE_JOB_ID = (
    "real-integration-fail-once"
)


class Command(BaseCommand):
    help = (
        "Run a real 500-job integration test using "
        "Redis and a real Celery worker."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--timeout",
            type=int,
            default=300,
            help=(
                "Maximum number of seconds to wait "
                "for all 500 jobs."
            ),
        )

    def handle(self, *args, **options):
        timeout = options["timeout"]

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

        redis_client = get_redis_client()

        self.stdout.write(
            self.style.WARNING(
                "\nREAL 500-JOB INTEGRATION TEST\n"
                "A real Celery worker must already be running.\n"
            )
        )

        self.stdout.write(
            f"Total jobs   : {TOTAL_JOBS}\n"
            f"Rate limit   : {rate_limit} emails "
            f"per {window_seconds} seconds\n"
            f"Timeout      : {timeout} seconds\n"
        )

        # ----------------------------------------------------
        # Clean test-specific state
        # ----------------------------------------------------

        redis_client.delete(
            PENDING_QUEUE_KEY,
            PROCESSING_QUEUE_KEY,
            DEAD_LETTER_QUEUE_KEY,
            DISPATCHER_LOCK_KEY,
            RATE_LIMIT_KEY,
        )

        clear_queue_metrics()
        start_queue_run()

        # ----------------------------------------------------
        # Create 500 real Redis jobs
        # ----------------------------------------------------

        submitted_job_ids = set()

        for index in range(1, TOTAL_JOBS + 1):
            if index == 250:
                job_id = INTENTIONAL_FAILURE_JOB_ID
                fail_once = True
            else:
                job_id = (
                    f"real-job-{index}-{uuid.uuid4().hex}"
                )
                fail_once = False

            submitted_job_ids.add(job_id)

            payload = {
                "job_id": job_id,
                "email": (
                    f"integration-{index}@example.com"
                ),
                "subject": (
                    f"Integration test email {index}"
                ),
                "message": (
                    f"Real integration test job {index}"
                ),
                "fail_once": fail_once,
                "always_fail": False,
            }

            redis_client.rpush(
                PENDING_QUEUE_KEY,
                json.dumps(payload),
            )

        actual_pending = get_pending_count()

        if actual_pending != TOTAL_JOBS:
            raise CommandError(
                "Submission failed: expected "
                f"{TOTAL_JOBS} pending jobs but found "
                f"{actual_pending}."
            )

        record_submitted(TOTAL_JOBS)

        self.stdout.write(
            self.style.SUCCESS(
                f"Submitted {TOTAL_JOBS} real jobs to Redis."
            )
        )

        # ----------------------------------------------------
        # Publish real dispatcher task to Celery
        # ----------------------------------------------------

        dispatcher_result = (
            dispatch_pending_emails.delay()
        )

        self.stdout.write(
            f"Dispatcher Celery task ID: "
            f"{dispatcher_result.id}\n"
        )

        # ----------------------------------------------------
        # Wait for completion
        # ----------------------------------------------------

        started_at = time.monotonic()
        last_completed = -1

        while True:
            completed_ids = (
                get_completed_job_ids()
            )

            completed_count = len(
                completed_ids
            )

            pending_count = redis_client.llen(
                PENDING_QUEUE_KEY
            )

            processing_count = redis_client.llen(
                PROCESSING_QUEUE_KEY
            )

            dead_letter_count = redis_client.llen(
                DEAD_LETTER_QUEUE_KEY
            )

            if completed_count != last_completed:
                self.stdout.write(
                    "Progress: "
                    f"completed={completed_count}, "
                    f"pending={pending_count}, "
                    f"processing={processing_count}, "
                    f"dead_letter={dead_letter_count}"
                )

                last_completed = completed_count

            if (
                completed_count
                + dead_letter_count
                == TOTAL_JOBS
                and pending_count == 0
                and processing_count == 0
            ):
                break

            elapsed = (
                time.monotonic()
                - started_at
            )

            if elapsed >= timeout:
                raise CommandError(
                    "\nTIMEOUT\n"
                    f"Completed   : {completed_count}\n"
                    f"Pending     : {pending_count}\n"
                    f"Processing  : {processing_count}\n"
                    f"Dead letter : {dead_letter_count}\n"
                )

            # This sleep is only polling the test observer.
            # It is NOT used by the rate limiter or worker.
            time.sleep(1)

        # ----------------------------------------------------
        # ASSERTION 1: no job lost
        # ----------------------------------------------------

        completed_ids = get_completed_job_ids()

        missing_job_ids = (
            submitted_job_ids
            - completed_ids
        )

        if missing_job_ids:
            raise CommandError(
                "NO-JOB-LOSS ASSERTION FAILED. "
                f"Missing jobs: {len(missing_job_ids)}"
            )

        if len(completed_ids) != TOTAL_JOBS:
            raise CommandError(
                "Expected exactly 500 completed jobs, "
                f"found {len(completed_ids)}."
            )

        # ----------------------------------------------------
        # ASSERTION 2: rate limit never exceeded
        # ----------------------------------------------------

        maximum_in_any_window = (
            get_max_dispatches_in_rolling_window(
                window_seconds
            )
        )

        if maximum_in_any_window > rate_limit:
            raise CommandError(
                "RATE-LIMIT ASSERTION FAILED. "
                f"Found {maximum_in_any_window} jobs inside "
                f"a rolling {window_seconds}-second "
                f"window. Limit is {rate_limit}."
            )

        # ----------------------------------------------------
        # ASSERTION 3: intentional failure was retried
        # ----------------------------------------------------

        retry_count = get_retry_count(
            INTENTIONAL_FAILURE_JOB_ID
        )

        if retry_count < 1:
            raise CommandError(
                "RETRY ASSERTION FAILED. "
                "Intentional temporary failure was "
                "not retried."
            )

        if (
            INTENTIONAL_FAILURE_JOB_ID
            not in completed_ids
        ):
            raise CommandError(
                "RETRY ASSERTION FAILED. "
                "Intentional failure never completed."
            )

        # ----------------------------------------------------
        # Final summary
        # ----------------------------------------------------

        elapsed = (
            time.monotonic()
            - started_at
        )

        self.stdout.write(
            self.style.SUCCESS(
                "\n"
                "============================================================\n"
                "REAL 500-JOB INTEGRATION TEST PASSED\n"
                "------------------------------------------------------------\n"
                f"Submitted jobs        : {TOTAL_JOBS}\n"
                f"Completed jobs        : {len(completed_ids)}\n"
                f"Lost jobs             : 0\n"
                f"Dead-letter jobs      : 0\n"
                f"Rate limit            : {rate_limit} / "
                f"{window_seconds} seconds\n"
                f"Max in rolling window : {maximum_in_any_window}\n"
                f"Intentional retries   : {retry_count}\n"
                f"Failed job completed  : YES\n"
                f"Elapsed time          : {elapsed:.2f} seconds\n"
                "============================================================"
            )
        )
