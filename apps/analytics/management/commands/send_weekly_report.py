"""
send_weekly_report.py

Generates and sends the automated weekly insights & sentiment report
to workspace owners and support managers.
Addresses Hackathon Problem Statement 2.5 Bonus Twist:
"Automatic weekly insights report on recurring complaints."
"""

from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings
from apps.workspaces.models import Workspace, WorkspaceMembership
from services.analytics.weekly_insights import weekly_insights_service


class Command(BaseCommand):
    help = "Generates and dispatches the weekly customer insights and recurring complaints report."

    def add_arguments(self, parser):
        parser.add_argument(
            "--workspace",
            type=str,
            help="Filter by specific workspace slug (e.g. shopease, expressbeas).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simulates generation and prints the report to stdout without sending emails.",
        )

    def handle(self, *args, **options):
        workspace_slug = options.get("workspace")
        dry_run = options.get("dry_run", False)

        workspaces = Workspace.objects.filter(status=Workspace.Status.ACTIVE)
        if workspace_slug:
            workspaces = workspaces.filter(slug=workspace_slug)

        if not workspaces.exists():
            self.stdout.write(self.style.WARNING("[-] No matching active workspaces found."))
            return

        self.stdout.write("\n[*] Generating Supporto AI Weekly Insights Reports...\n")

        for ws in workspaces:
            self.stdout.write(f"  -> Processing: {ws.name} (/{ws.slug}/)")
            report = weekly_insights_service.get_weekly_report(ws)

            # Resolve recipients: Workspace Owners + Support Email
            owners = WorkspaceMembership.objects.filter(
                workspace=ws,
                role=WorkspaceMembership.Role.OWNER,
                is_active=True
            ).select_related("user")

            recipient_emails = set()
            for m in owners:
                if m.user and m.user.email:
                    recipient_emails.add(m.user.email)

            if hasattr(ws, "settings") and ws.settings.support_email:
                recipient_emails.add(ws.settings.support_email)

            if not recipient_emails:
                recipient_emails.add("support@supporto.ai")

            subject = f"[Supporto AI] Weekly Customer Insights & Recurring Complaints: {ws.name}"

            # Plain text body
            complaint_lines = []
            for rc in report.get("recurring_complaints", []):
                q_text = ""
                if rc.get("sample_quotes"):
                    q_text = " - Sample: " + " | ".join(rc["sample_quotes"])
                complaint_lines.append(f"  * {rc['category']}: {rc['count']} tickets ({rc['percentage']}% share){q_text}")
            complaints_formatted = "\n".join(complaint_lines) if complaint_lines else "  No major complaint patterns recorded."

            sentiment_lines = [f"  * {k}: {v}" for k, v in report.get("sentiments", {}).items()]
            sentiments_formatted = "\n".join(sentiment_lines)

            body = (
                f"Supporto AI - Weekly Executive Customer Support Report\n"
                f"Workspace: {ws.name}\n"
                f"Reporting Period: {report['period']}\n"
                f"{'='*60}\n\n"
                f"EXECUTIVE SUMMARY:\n{report['summary_text']}\n\n"
                f"KEY METRICS:\n"
                f"  * Incoming Emails: {report['total_emails']}\n"
                f"  * Live Chat & Voice Sessions: {report['total_conversations']}\n"
                f"  * Total Tickets: {report['total_tickets']}\n"
                f"  * Staff Approved Proposals: {report['tickets_approved']}\n"
                f"  * Urgent / Escalated Issues: {report['urgent_count']}\n"
                f"  * Average Resolution Time: {report['avg_resolution_hours']} hours\n\n"
                f"RECURRING COMPLAINT TOPICS & CATEGORY SHARE:\n"
                f"{complaints_formatted}\n\n"
                f"CUSTOMER SENTIMENT DISTRIBUTION:\n"
                f"{sentiments_formatted}\n\n"
                f"{'='*60}\n"
                f"View the live interactive dashboard: /{ws.slug}/analytics/weekly/\n"
                f"Generated automatically by Supporto AI Autonomous Triage Engine.\n"
            )

            if dry_run:
                self.stdout.write(self.style.SUCCESS(f"    [DRY RUN] Would send to: {', '.join(recipient_emails)}"))
                self.stdout.write(f"    Subject: {subject}")
                self.stdout.write(f"    Total Interactions: {report['total_emails'] + report['total_conversations']}")
            else:
                try:
                    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "support@supporto.ai")
                    send_mail(
                        subject=subject,
                        message=body,
                        from_email=from_email,
                        recipient_list=list(recipient_emails),
                        fail_silently=False,
                    )
                    self.stdout.write(self.style.SUCCESS(f"    [+] Report dispatched to {len(recipient_emails)} recipient(s): {', '.join(recipient_emails)}"))
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"    [!] Email send failed ({e}), printed to log."))

        self.stdout.write(self.style.SUCCESS("\n[+] Weekly reports batch processing complete!\n"))

