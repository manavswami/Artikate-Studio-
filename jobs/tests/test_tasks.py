from unittest.mock import patch

from celery.exceptions import Retry
from django.test import SimpleTestCase

from jobs.tasks import send_transactional_email


class SendTransactionalEmailTests(SimpleTestCase):
    """
    Tests individual email task behaviour.
    """

    def get_task_kwargs(self, **overrides):
        kwargs = {
            "job_id": "job-1",
            "email": "test@example.com",
            "subject": "Test subject",
            "message": "Test message",
            "processing_payload": (
                '{"job_id": "job-1"}'
            ),
            "fail_once": False,
            "always_fail": False,
        }

        kwargs.update(overrides)

        return kwargs

    @patch(
        "jobs.tasks.record_completed"
    )
    @patch(
        "jobs.tasks.remove_from_processing"
    )
    @patch(
        "jobs.tasks.send_mail"
    )
    def test_successful_email_is_removed_from_processing(
        self,
        mock_send_mail,
        mock_remove,
        mock_record_completed,
    ):
        result = send_transactional_email.run(
            **self.get_task_kwargs()
        )

        mock_send_mail.assert_called_once()

        mock_remove.assert_called_once_with(
            '{"job_id": "job-1"}'
        )

        self.assertEqual(
            result["status"],
            "sent",
        )

    @patch(
        "jobs.tasks.record_retry"
    )
    @patch(
        "jobs.tasks.send_mail"
    )
    def test_temporary_failure_uses_exponential_backoff(
        self,
        mock_send_mail,
        mock_record_retry,
    ):
        mock_send_mail.side_effect = RuntimeError(
            "Temporary provider failure."
        )

        with patch.object(
            send_transactional_email,
            "retry",
            side_effect=Retry(),
        ) as mock_retry:

            with self.assertRaises(Retry):
                send_transactional_email.run(
                    **self.get_task_kwargs()
                )

            retry_kwargs = (
                mock_retry.call_args.kwargs
            )

            # First retry:
            # 5 * (2 ** 0) = 5 seconds.
            self.assertEqual(
                retry_kwargs["countdown"],
                5,
            )

    @patch(
        "jobs.tasks.record_retry"
    )
    @patch(
        "jobs.tasks.send_mail"
    )
    def test_retry_receives_original_exception(
        self,
        mock_send_mail,
        mock_record_retry,
    ):
        error = RuntimeError(
            "Provider unavailable."
        )

        mock_send_mail.side_effect = error

        with patch.object(
            send_transactional_email,
            "retry",
            side_effect=Retry(),
        ) as mock_retry:

            with self.assertRaises(Retry):
                send_transactional_email.run(
                    **self.get_task_kwargs()
                )

            self.assertIs(
                mock_retry.call_args.kwargs["exc"],
                error,
            )

    @patch(
        "jobs.tasks.record_failed"
    )
    @patch(
        "jobs.tasks.move_processing_to_dead_letter"
    )
    @patch(
        "jobs.tasks.send_mail"
    )
    def test_permanent_failure_moves_job_to_dead_letter(
        self,
        mock_send_mail,
        mock_dead_letter,
        mock_record_failed,
    ):
        """
        Simulate the task already being at maximum retries.
        """

        mock_send_mail.side_effect = RuntimeError(
            "Permanent provider failure."
        )

        with patch.object(
            send_transactional_email.request,
            "retries",
            3,
        ):
            result = send_transactional_email.run(
                **self.get_task_kwargs()
            )

        mock_dead_letter.assert_called_once_with(
            '{"job_id": "job-1"}'
        )

        self.assertEqual(
            result["status"],
            "dead-lettered",
        )

    def test_task_configuration_uses_late_acknowledgement(self):
        self.assertTrue(
            send_transactional_email.acks_late
        )

        self.assertTrue(
            send_transactional_email.reject_on_worker_lost
        )

        self.assertEqual(
            send_transactional_email.max_retries,
            3,
        )
