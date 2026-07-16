from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from jobs.rate_limiter import (
    RATE_LIMIT_KEY,
    acquire_rate_limit_slot,
    get_rate_limit_status,
)


# @override_settings(
#     EMAIL_RATE_LIMIT=4,
#     EMAIL_RATE_WINDOW_SECONDS=60,
# )
class EmailRateLimiterTests(SimpleTestCase):
    """
    Tests the global Redis-backed rolling-window rate limiter.
    """

    def setUp(self):
        patcher = patch(
            "jobs.rate_limiter.get_redis_client"
        )

        self.mock_get_redis_client = patcher.start()
        self.addCleanup(patcher.stop)

        self.redis = (
            self.mock_get_redis_client.return_value
        )

    def test_available_slot_is_acquired(self):
        self.redis.eval.return_value = [1, 0]

        allowed, retry_after = (
            acquire_rate_limit_slot()
        )

        self.assertTrue(allowed)
        self.assertEqual(retry_after, 0)

    def test_full_rate_limit_returns_retry_after(self):
        self.redis.eval.return_value = [0, 42]

        allowed, retry_after = (
            acquire_rate_limit_slot()
        )

        self.assertFalse(allowed)
        self.assertEqual(retry_after, 42)

    def test_rate_limiter_uses_single_atomic_lua_operation(self):
        self.redis.eval.return_value = [1, 0]

        acquire_rate_limit_slot()

        self.redis.eval.assert_called_once()

        call_args = self.redis.eval.call_args.args

        # One Redis key is supplied to the Lua script.
        self.assertEqual(
            call_args[1],
            1,
        )

        self.assertEqual(
            call_args[2],
            RATE_LIMIT_KEY,
        )

    def test_configured_limit_and_window_are_passed_to_redis(self):
        self.redis.eval.return_value = [1, 0]

        acquire_rate_limit_slot()

        call_args = self.redis.eval.call_args.args

        # Structure:
        #
        # eval(
        #     lua_script,
        #     1,
        #     RATE_LIMIT_KEY,
        #     now,
        #     window_seconds,
        #     limit,
        #     member,
        # )

        self.assertEqual(
            call_args[4],
            60,
        )

        self.assertEqual(
            call_args[5],
            200,
        )

    @patch("jobs.rate_limiter.time.time", return_value=100.0)
    def test_status_reports_full_window_and_next_slot_time(
        self,
        mock_time,
    ):
        self.redis.zcard.return_value = 200
        self.redis.zrange.return_value = [
            ("oldest-reservation", 45.1),
        ]

        status = get_rate_limit_status()

        self.assertEqual(status["used"], 200)
        self.assertEqual(status["remaining"], 0)
        self.assertEqual(status["retry_after"], 6)

        self.redis.zremrangebyscore.assert_called_once_with(
            RATE_LIMIT_KEY,
            "-inf",
            40.0,
        )
