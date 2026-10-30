from datetime import timedelta
from django.test import TestCase, Client
from django.utils import timezone
from apps.workspaces.models import Workspace, WorkspaceMembership, WorkspaceAuthorizedEmail
from apps.accounts.models import User
from apps.teams.models import Team
from apps.emails.models import InboundEmail, TicketProposal
from apps.tickets.models import Ticket
from apps.customers.models import Customer
from services.analytics.weekly_insights import weekly_insights_service

class WeeklyInsightsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.workspace = Workspace.objects.create(name="ShopEase", slug="shopease")
        self.user = User.objects.create_user(
            email="agent@shopease.com",
            password="StrongPassword123!",
            first_name="Jane",
            last_name="Agent"
        )
        WorkspaceAuthorizedEmail.objects.create(
            workspace=self.workspace,
            email="agent@shopease.com",
            assigned_role=WorkspaceMembership.Role.AGENT,
            status=WorkspaceAuthorizedEmail.Status.AUTHORIZED,
            linked_user=self.user,
        )
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=self.user,
            role=WorkspaceMembership.Role.AGENT,
            is_active=True,
        )
        self.team = Team.objects.create(workspace=self.workspace, name="Order Support", slug="order-support")

    def test_empty_dataset_handles_gracefully(self):
        report = weekly_insights_service.get_weekly_report(self.workspace)
        self.assertEqual(report["total_emails"], 0)
        self.assertEqual(report["total_tickets"], 0)
        self.assertEqual(report["tickets_approved"], 0)
        self.assertEqual(report["tickets_rejected"], 0)
        self.assertEqual(report["avg_resolution_hours"], 0.0)
        self.assertIn("No customer interactions or tickets were recorded", report["summary_text"])

    def test_metrics_calculation_with_real_records(self):
        customer = Customer.objects.create(
            workspace=self.workspace,
            email="shopper@example.com",
            name="Alice Shopper"
        )
        # Create an inbound email
        inbound = InboundEmail.objects.create(
            workspace=self.workspace,
            sender_email="shopper@example.com",
            sender_name="Alice Shopper",
            subject="Delayed Package",
            original_text_body="Where is my order? It was supposed to arrive yesterday.",
            normalized_text_body="Where is my order? It was supposed to arrive yesterday.",
            provider_message_id="msg-1001",
            received_at=timezone.now(),
        )
        # Create an approved proposal
        proposal = TicketProposal.objects.create(
            workspace=self.workspace,
            inbound_email=inbound,
            customer=customer,
            proposed_subject="Delayed Package Inquiry",
            proposed_description="Customer asking where order is",
            proposed_priority=Ticket.Priority.HIGH,
            proposed_category="Order Status",
            ai_sentiment="NEGATIVE",
            ai_urgency="HIGH",
            approval_status=TicketProposal.ApprovalStatus.APPROVED,
        )
        # Create a ticket resolved 2 hours after creation
        now = timezone.now()
        ticket = Ticket.objects.create(
            workspace=self.workspace,
            customer=customer,
            assigned_team=self.team,
            ticket_number="TICK-TEST-101",
            subject="Delayed Package Inquiry",
            description="Detailed ticket description",
            priority=Ticket.Priority.HIGH,
            category="Order Status",
            status=Ticket.Status.RESOLVED,
            resolved_at=now,
        )
        Ticket.objects.filter(id=ticket.id).update(created_at=now - timedelta(hours=2))

        report = weekly_insights_service.get_weekly_report(self.workspace)
        self.assertEqual(report["total_emails"], 1)
        self.assertEqual(report["total_tickets"], 1)
        self.assertEqual(report["tickets_approved"], 1)
        self.assertEqual(report["tickets_rejected"], 0)
        self.assertEqual(report["sentiments"]["NEGATIVE"], 1)
        self.assertGreaterEqual(report["avg_resolution_hours"], 1.9)
        self.assertIn("ShopEase", report["summary_text"])
        self.assertIn("Order Status", report["summary_text"])

    def test_csv_export_format(self):
        report = weekly_insights_service.get_weekly_report(self.workspace)
        csv_text = weekly_insights_service.export_csv(report)
        self.assertIn("Metric,Value", csv_text)
        self.assertIn("Total Incoming Emails", csv_text)
        self.assertIn("Sentiment,Count", csv_text)
        self.assertIn("Team,Assigned This Week,Active Backlog", csv_text)

    def test_weekly_insights_view_authorized_and_csv_export(self):
        self.client.force_login(self.user)
        # Standard page view
        res = self.client.get(f"/{self.workspace.slug}/analytics/weekly/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Weekly Executive Insights")
        self.assertContains(res, "Export Report (CSV)")

        # CSV download view
        csv_res = self.client.get(f"/{self.workspace.slug}/analytics/weekly/?export=csv")
        self.assertEqual(csv_res.status_code, 200)
        self.assertEqual(csv_res["Content-Type"], "text/csv")
        self.assertIn('filename="shopease_weekly_insights.csv"', csv_res["Content-Disposition"])
