import time
from datetime import datetime, timezone

from django.core.management.base import BaseCommand, CommandError

from jobs.pending_queue import (
    dispatcher_is_locked,
    get_dead_letter_count,
    get_max_dispatches_in_rolling_window,
    get_pending_count,
    get_processing_count,
    get_queue_metrics,
)
from jobs.rate_limiter import get_rate_limit_status


class Command(BaseCommand):
    help = (
        "Show queue, rate-limit, and outcome metrics. "
        "Use --watch during a live demo."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--watch",
            action="store_true",
            help="Print a new snapshot until interrupted with Ctrl+C.",
        )
        parser.add_argument(
            "--interval",
            type=float,
            default=1.0,
            help="Seconds between snapshots when --watch is used (default: 1).",
        )
        parser.add_argument(
            "--iterations",
            type=int,
            help=(
                "Stop after this many snapshots. Useful with --watch for "
                "a bounded terminal capture."
            ),
        )

    def _snapshot(self):
        rate = get_rate_limit_status()
        maximum = get_max_dispatches_in_rolling_window(
            rate["window_seconds"]
        )
        metrics = get_queue_metrics()

        return {
            "pending": get_pending_count(),
            "processing": get_processing_count(),
            "dead_letter": get_dead_letter_count(),
            "dispatcher_active": dispatcher_is_locked(),
            **metrics,
            "rate": rate,
            "max_rolling": maximum,
        }

    def _write_snapshot(self, snapshot):
        rate = snapshot["rate"]
        now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        max_ok = snapshot["max_rolling"] <= rate["limit"]
        status = "PASS" if max_ok else "BREACH"

        self.stdout.write(
            "\n"
            f"[{now}] LIVE EMAIL QUEUE SNAPSHOT\n"
            "------------------------------------------------------------\n"
            f"Queue state       pending={snapshot['pending']}, "
            f"processing={snapshot['processing']}, "
            f"dead_letter={snapshot['dead_letter']}\n"
            f"Dispatcher lock   {'ACTIVE' if snapshot['dispatcher_active'] else 'IDLE'}\n"
            f"Job lifecycle     submitted={snapshot['submitted']}, "
            f"dispatched={snapshot['dispatched']}, "
            f"completed={snapshot['completed']}, "
            f"retries={snapshot['retries']}, "
            f"failed={snapshot['failed']}\n"
            f"Rate window       used={rate['used']}/{rate['limit']} jobs in "
            f"the last {rate['window_seconds']:g}s; "
            f"remaining={rate['remaining']}; "
            f"next slot in={rate['retry_after']}s\n"
            f"Rate audit        max rolling window={snapshot['max_rolling']}/"
            f"{rate['limit']} -> {status}\n"
            f"Run timing        elapsed={snapshot['elapsed']}s; "
            f"completed throughput={snapshot['throughput']} jobs/s\n"
            "------------------------------------------------------------"
        )

    def handle(self, *args, **options):
        watch = options["watch"]
        interval = options["interval"]
        iterations = options["iterations"]

        if interval <= 0:
            raise CommandError("--interval must be greater than zero.")

        if iterations is not None and iterations < 1:
            raise CommandError("--iterations must be at least 1.")

        if iterations is not None and not watch:
            raise CommandError("--iterations requires --watch.")

        if watch:
            self.stdout.write(
                "Watching live queue state. Press Ctrl+C to stop."
            )

        snapshots_written = 0

        try:
            while True:
                self._write_snapshot(self._snapshot())
                snapshots_written += 1

                if not watch:
                    return

                if (
                    iterations is not None
                    and snapshots_written >= iterations
                ):
                    return

                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write("\nStopped live queue monitor.")
