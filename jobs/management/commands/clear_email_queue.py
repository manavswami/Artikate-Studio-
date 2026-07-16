from django.core.management.base import BaseCommand

from jobs.pending_queue import (
    DEAD_LETTER_EMAIL_QUEUE_KEY,
    DISPATCHER_LOCK_KEY,
    PENDING_EMAIL_QUEUE_KEY,
    PROCESSING_EMAIL_QUEUE_KEY,
    clear_queue_metrics,
    get_redis_client,
)
from jobs.rate_limiter import RATE_LIMIT_KEY


class Command(BaseCommand):
    help = "Clear email queues, rate-limit state, and dispatcher lock."

    def add_arguments(self, parser):
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Skip confirmation.",
        )

        parser.add_argument(
            "--include-dead-letter",
            action="store_true",
            help="Also clear permanently failed jobs.",
        )

    def handle(self, *args, **options):
        client = get_redis_client()

        pending = client.llen(
            PENDING_EMAIL_QUEUE_KEY
        )

        processing = client.llen(
            PROCESSING_EMAIL_QUEUE_KEY
        )

        dead_letter = client.llen(
            DEAD_LETTER_EMAIL_QUEUE_KEY
        )

        self.stdout.write(
            f"Pending:     {pending}"
        )

        self.stdout.write(
            f"Processing:  {processing}"
        )

        self.stdout.write(
            f"Dead-letter: {dead_letter}"
        )

        if not options["yes"]:
            answer = input(
                "Clear email queue state? [y/N]: "
            )

            if answer.lower() not in ("y", "yes"):
                self.stdout.write("Cancelled.")
                return

        keys_to_delete = [
            PENDING_EMAIL_QUEUE_KEY,
            PROCESSING_EMAIL_QUEUE_KEY,
            DISPATCHER_LOCK_KEY,
            RATE_LIMIT_KEY,
        ]

        if options["include_dead_letter"]:
            keys_to_delete.append(
                DEAD_LETTER_EMAIL_QUEUE_KEY
            )

        client.delete(
            *keys_to_delete
        )
        clear_queue_metrics()

        self.stdout.write(
            self.style.SUCCESS(
                "Email queue state cleared."
            )
        )
        self.stdout.write(
            "Live queue metrics and rate-limit audit history were cleared."
        )

        if not options["include_dead_letter"]:
            self.stdout.write(
                "Dead-letter queue was preserved."
            )
