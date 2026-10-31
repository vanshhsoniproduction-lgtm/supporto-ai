from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Clears ALL application data from the database (preserves migrations and schema)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Skip confirmation prompt and clear immediately.",
        )

    def handle(self, *args, **options):
        if not options["yes"]:
            confirm = input(
                "\n[!] This will DELETE ALL data from the database.\n"
                "    Migrations and schema will be preserved.\n"
                "    Type 'yes' to confirm: "
            ).strip().lower()
            if confirm != "yes":
                self.stdout.write(self.style.WARNING("Aborted. No data was deleted."))
                return

        # Order matters — delete child tables before parents (FK constraints)
        tables_to_clear = [
            # Analytics / Audit
            "analytics_auditlog",
            # Emails
            "emails_ticketproposal",
            "emails_inboundemail",
            "emails_mailboxconnection",
            # Tickets
            "tickets_ticketevent",
            "tickets_ticketcomment",
            "tickets_ticketassignment",
            "tickets_ticket",
            # Conversations / Messages
            "conversations_message",
            "conversations_conversation",
            # Customers
            "customers_customer",
            # Knowledge Base
            "knowledge_base_knowledgechunk",
            "knowledge_base_knowledgedocument",
            # Voice Support
            "voice_support_ivroption",
            "voice_support_ivrmenu",
            "voice_support_voiceconfiguration",
            # AI Engine
            "ai_engine_agentconfiguration",
            # Teams
            "teams_teammembership",
            "teams_team",
            # Workspaces
            "workspaces_workspacewebhook",
            "workspaces_workspaceauthorizedemail",
            "workspaces_workspacemembership",
            "workspaces_workspacesettings",
            "workspaces_workspace",
            # Accounts (non-superuser users)
            "accounts_user",
        ]

        cleared = []
        errors = []

        with connection.cursor() as cursor:
            # Disable FK checks for SQLite
            try:
                cursor.execute("PRAGMA foreign_keys = OFF;")
            except Exception:
                pass

            for table in tables_to_clear:
                try:
                    cursor.execute(f"DELETE FROM {table};")
                    cleared.append(table)
                except Exception as e:
                    errors.append(f"  [!] {table}: {e}")

            try:
                cursor.execute("PRAGMA foreign_keys = ON;")
            except Exception:
                pass

        self.stdout.write(self.style.SUCCESS(f"\n[+] Cleared {len(cleared)} tables successfully."))

        if errors:
            self.stdout.write(self.style.WARNING("\nTables with errors (may not exist yet):"))
            for err in errors:
                self.stdout.write(self.style.WARNING(err))

        self.stdout.write(
            "\n[>] Run: python manage.py seed_demo\n"
            "   to re-populate the database with fresh demo data.\n"
        )
