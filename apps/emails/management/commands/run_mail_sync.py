import time
import sys
from django.core.management.base import BaseCommand
from apps.emails.models import MailboxConnection
from apps.emails.services.gmail_service import gmail_service

class Command(BaseCommand):
    help = "Continuously synchronizes connected mailboxes at a specified interval."

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=int, default=30, help="Polling interval in seconds (default: 30)")
        parser.add_argument("--workspace", type=str, help="Optional workspace slug filter")

    def handle(self, *args, **options):
        interval = options["interval"]
        ws_slug = options.get("workspace")
        self.stdout.write(self.style.SUCCESS(f"[*] Supporto AI Mail Sync Daemon started (Interval: {interval}s). Press Ctrl+C to terminate."))

        try:
            while True:
                qs = MailboxConnection.objects.filter(status=MailboxConnection.Status.ACTIVE).select_related("workspace")
                if ws_slug:
                    qs = qs.filter(workspace__slug=ws_slug)

                active_count = qs.count()
                now_str = time.strftime("%Y-%m-%d %H:%M:%S")

                if active_count > 0:
                    self.stdout.write(f"[{now_str}] Checking {active_count} active mailbox(es)...")
                    for conn in qs:
                        try:
                            count = gmail_service.sync_mailbox(conn)
                            if count > 0:
                                self.stdout.write(self.style.SUCCESS(f"  [+] {conn.email_address}: Synced and triaged {count} new email(s)."))
                        except Exception as e:
                            self.stdout.write(self.style.ERROR(f"  [-] Error syncing {conn.email_address}: {e}"))
                else:
                    self.stdout.write(f"[{now_str}] Idle (0 active mailboxes configured).")

                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\n[*] Mail sync daemon terminated gracefully."))

