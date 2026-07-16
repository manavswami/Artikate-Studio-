import json
from unittest.mock import MagicMock, patch

from celery.exceptions import Retry
from django.test import SimpleTestCase

from jobs.tasks import dispatch_pending_emails


class EmailDispatcherTests(SimpleTestCase):
    """
    Tests the bounded email dispatcher.

    Important behaviour:

    - Pending emails remain in Redis until rate-limit capacity exists.
    - Only emails allowed by current capacity become Celery tasks.
    - Only one dispatcher can process the queue at a time.
    - When rate-limited, the dispatcher retries later.
    """

    @patch("jobs.tasks.record_dispatched")
    @patch("jobs.tasks.release_dispatcher_lock")
    @patch("jobs.tasks.send_transactional_email")
    @patch("jobs.tasks.move_next_job_to_processing")
    @patch("jobs.tasks.acquire_rate_limit_slot")
    @patch("jobs.tasks.get_pending_count")
    @patch("jobs.tasks.acquire_dispatcher_lock")
    def test_one_available_slot_creates_only_one_email_task(
        self,
        mock_acquire_lock,
        mock_pending_count,
        mock_acquire_slot,
        mock_move_job,
        mock_send_task,
        mock_release_lock,
        mock_record_dispatched,
    ):
        """
        Scenario:

            100 emails are waiting in Redis.

            Only one email should be dispatched during
            this test execution.

        Expected:

            Exactly one individual Celery email task is created.
        """

        mock_acquire_lock.return_value = "lock-token"

        # tasks.py calls get_pending_count() multiple times:
        #
        # Call 1:
        #     initial_pending = get_pending_count()
        #     -> 100
        #
        # Call 2:
        #     while get_pending_count() > 0
        #     -> 100, enter loop
        #
        # Call 3:
        #     logging after dispatch
        #     -> 99
        #
        # Call 4:
        #     while condition again
        #     -> 0, stop
        #
        # Any additional calls also return 0.

        pending_values = iter([
            100,
            100,
            99,
            0,
        ])

        def pending_count():
            return next(
                pending_values,
                0,
            )

        mock_pending_count.side_effect = pending_count

        # One rate-limit slot is available.
        mock_acquire_slot.return_value = (
            True,
            0,
        )

        raw_job = json.dumps(
            {
                "job_id": "job-1",
                "email": "test@example.com",
                "subject": "Test",
                "message": "Hello",
            }
        )

        mock_move_job.return_value = raw_job

        mock_result = MagicMock()
        mock_result.id = "celery-task-1"

        mock_send_task.delay.return_value = mock_result

        result = dispatch_pending_emails.run()

        # Exactly one individual email task must be created.
        self.assertEqual(
            mock_send_task.delay.call_count,
            1,
        )

        self.assertEqual(
            result["status"],
            "complete",
        )

        self.assertEqual(
            result["dispatched"],
            1,
        )

        mock_release_lock.assert_called_once_with(
            "lock-token"
        )

    @patch("jobs.tasks.get_pending_count")
    @patch("jobs.tasks.acquire_dispatcher_lock")
    def test_second_dispatcher_does_not_process_queue(
        self,
        mock_acquire_lock,
        mock_pending_count,
    ):
        """
        If another dispatcher already owns the Redis lock,
        this dispatcher exits immediately.
        """

        mock_acquire_lock.return_value = None
        mock_pending_count.return_value = 100

        result = dispatch_pending_emails.run()

        self.assertEqual(
            result["status"],
            "already-running",
        )

        self.assertEqual(
            result["dispatched"],
            0,
        )

    @patch("jobs.tasks.refresh_dispatcher_lock")
    @patch("jobs.tasks.acquire_rate_limit_slot")
    @patch("jobs.tasks.get_pending_count")
    @patch("jobs.tasks.acquire_dispatcher_lock")
    def test_dispatcher_retries_when_rate_limit_is_full(
        self,
        mock_acquire_lock,
        mock_pending_count,
        mock_acquire_slot,
        mock_refresh_lock,
    ):
        """
        Scenario:

            99 emails remain pending.
            Global rate limit is currently full.

        Expected:

            - No individual email task is created.
            - Dispatcher retries after the Redis-provided delay.
            - Pending emails remain dormant in Redis.
        """

        mock_acquire_lock.return_value = "lock-token"

        mock_pending_count.return_value = 99

        mock_acquire_slot.return_value = (
            False,
            60,
        )

        with patch.object(
            dispatch_pending_emails,
            "retry",
            side_effect=Retry(),
        ) as mock_retry:

            with self.assertRaises(Retry):
                dispatch_pending_emails.run()

            mock_retry.assert_called_once()

            retry_kwargs = mock_retry.call_args.kwargs

            self.assertEqual(
                retry_kwargs["countdown"],
                60,
            )

            self.assertEqual(
                retry_kwargs["kwargs"],
                {
                    "lock_token": "lock-token",
                },
            )

        mock_refresh_lock.assert_called_once_with(
            "lock-token"
        )

    @patch("jobs.tasks.release_dispatcher_lock")
    @patch("jobs.tasks.get_pending_count")
    @patch("jobs.tasks.acquire_dispatcher_lock")
    def test_empty_queue_releases_dispatcher_lock(
        self,
        mock_acquire_lock,
        mock_pending_count,
        mock_release_lock,
    ):
        """
        When no pending emails remain, the dispatcher completes
        and releases its Redis lock.
        """

        mock_acquire_lock.return_value = "lock-token"

        mock_pending_count.return_value = 0

        result = dispatch_pending_emails.run()

        self.assertEqual(
            result["status"],
            "complete",
        )

        self.assertEqual(
            result["dispatched"],
            0,
        )

        self.assertEqual(
            result["pending"],
            0,
        )

        mock_release_lock.assert_called_once_with(
            "lock-token"
        )
