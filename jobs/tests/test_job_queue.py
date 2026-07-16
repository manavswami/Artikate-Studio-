import json
from unittest.mock import patch

from django.test import SimpleTestCase

from jobs.pending_queue import (
    DEAD_LETTER_EMAIL_QUEUE_KEY,
    DISPATCHER_LOCK_KEY,
    PENDING_EMAIL_QUEUE_KEY,
    PROCESSING_EMAIL_QUEUE_KEY,
    acquire_dispatcher_lock,
    enqueue_email,
    move_next_job_to_processing,
    move_processing_to_dead_letter,
    release_dispatcher_lock,
)


class EmailJobQueueTests(SimpleTestCase):
    """
    Tests Redis-backed pending, processing, dead-letter,
    and dispatcher-lock behaviour.
    """

    def setUp(self):
        patcher = patch(
            "jobs.pending_queue.get_redis_client"
        )

        self.mock_get_redis_client = patcher.start()
        self.addCleanup(patcher.stop)

        self.redis = (
            self.mock_get_redis_client.return_value
        )

    def test_enqueue_email_adds_job_to_pending_queue(self):
        payload = enqueue_email(
            email="test@example.com",
            subject="Hello",
            message="Test message",
        )

        self.assertIn("job_id", payload)

        expected_raw_job = json.dumps(payload)

        self.redis.rpush.assert_called_once_with(
            PENDING_EMAIL_QUEUE_KEY,
            expected_raw_job,
        )

    def test_each_generated_job_id_is_unique(self):
        first = enqueue_email(
            email="first@example.com",
            subject="First",
            message="First message",
        )

        second = enqueue_email(
            email="second@example.com",
            subject="Second",
            message="Second message",
        )

        self.assertNotEqual(
            first["job_id"],
            second["job_id"],
        )

    def test_move_next_job_to_processing_uses_atomic_lua(self):
        raw_job = json.dumps(
            {
                "job_id": "job-1",
                "email": "test@example.com",
            }
        )

        self.redis.eval.return_value = raw_job

        result = move_next_job_to_processing()

        self.assertEqual(
            result,
            raw_job,
        )

        self.redis.eval.assert_called_once()

        call_args = self.redis.eval.call_args.args

        # Number of Redis keys passed to Lua.
        self.assertEqual(
            call_args[1],
            2,
        )

        self.assertEqual(
            call_args[2],
            PENDING_EMAIL_QUEUE_KEY,
        )

        self.assertEqual(
            call_args[3],
            PROCESSING_EMAIL_QUEUE_KEY,
        )

    def test_move_processing_to_dead_letter_is_atomic(self):
        raw_job = json.dumps(
            {
                "job_id": "failed-job",
            }
        )

        self.redis.eval.return_value = 1

        result = move_processing_to_dead_letter(
            raw_job
        )

        self.assertEqual(result, 1)

        self.redis.eval.assert_called_once()

        call_args = self.redis.eval.call_args.args

        self.assertEqual(
            call_args[1],
            2,
        )

        self.assertEqual(
            call_args[2],
            PROCESSING_EMAIL_QUEUE_KEY,
        )

        self.assertEqual(
            call_args[3],
            DEAD_LETTER_EMAIL_QUEUE_KEY,
        )

        self.assertEqual(
            call_args[4],
            raw_job,
        )

    def test_only_one_dispatcher_can_acquire_lock(self):
        self.redis.set.side_effect = [
            True,
            None,
        ]

        first_token = acquire_dispatcher_lock()
        second_token = acquire_dispatcher_lock()

        self.assertIsNotNone(first_token)
        self.assertIsNone(second_token)

        first_call = self.redis.set.call_args_list[0]

        self.assertEqual(
            first_call.args[0],
            DISPATCHER_LOCK_KEY,
        )

        self.assertTrue(
            first_call.kwargs["nx"]
        )

    def test_dispatcher_lock_release_is_owner_safe(self):
        self.redis.eval.return_value = 1

        result = release_dispatcher_lock(
            "owner-token"
        )

        self.assertTrue(result)

        call_args = self.redis.eval.call_args.args

        self.assertEqual(
            call_args[2],
            DISPATCHER_LOCK_KEY,
        )

        self.assertEqual(
            call_args[3],
            "owner-token",
        )