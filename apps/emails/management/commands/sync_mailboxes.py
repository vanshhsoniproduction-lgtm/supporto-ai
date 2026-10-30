import sys
from django.core.management.base import BaseCommand
from apps.emails.models import MailboxConnection
from apps.emails.services.gmail_service import gmail_service

class Command(BaseCommand):
    help = "Performs a single synchronization cycle for all active connected mailboxes."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", default=True, help="Run once and exit (default)")
        parser.add_argument("--workspace", type=str, help="Optional workspace slug filter")

    def handle(self, *args, **options):
        self.stdout.write("[*] Starting Supporto AI Mailbox Synchronization cycle...")
        qs = MailboxConnection.objects.filter(status=MailboxConnection.Status.ACTIVE).select_related("workspace")

        ws_slug = options.get("workspace")
        if ws_slug:
            qs = qs.filter(workspace__slug=ws_slug)

        count = qs.count()
        if count == 0:
            self.stdout.write(self.style.WARNING("[-] No active mailbox connections found. Connect mailboxes via Company Settings > Email Integration."))
            return

        self.stdout.write(f"[+] Found {count} active mailbox connection(s).")
        total_synced = 0

        for conn in qs:
            self.stdout.write(f"  -> Syncing {conn.email_address} ({conn.workspace.name})...")
            try:
                synced = gmail_service.sync_mailbox(conn)
                total_synced += synced
                self.stdout.write(self.style.SUCCESS(f"     [OK] Synced {synced} new email(s)."))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"     [ERR] {e}"))

        self.stdout.write(self.style.SUCCESS(f"[+] Sync cycle complete. Total new emails processed: {total_synced}"))

