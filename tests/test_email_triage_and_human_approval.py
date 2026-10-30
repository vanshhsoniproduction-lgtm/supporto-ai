from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.utils import timezone
from apps.workspaces.models import Workspace, WorkspaceMembership
from apps.teams.models import Team, TeamMembership
from apps.customers.models import Customer
from apps.tickets.models import Ticket
from apps.emails.models import MailboxConnection, InboundEmail, TicketProposal
from apps.emails.services.email_triage import email_triage_service

User = get_user_model()

class EmailTriageAndApprovalTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.password = "ApprovalPass123!"

        self.workspace = Workspace.objects.create(name="ShopEase", slug="shopease")
        self.manager = User.objects.create_user(email="manager@shopease.com", password=self.password)
        WorkspaceMembership.objects.create(workspace=self.workspace, user=self.manager, role=WorkspaceMembership.Role.MANAGER)

        self.team_billing = Team.objects.create(workspace=self.workspace, name="Billing Support", slug="billing-support")
        self.team_order = Team.objects.create(workspace=self.workspace, name="Order Support", slug="order-support")

        self.agent_billing = User.objects.create_user(email="billing.agent@shopease.com", password=self.password)
        WorkspaceMembership.objects.create(workspace=self.workspace, user=self.agent_billing, role=WorkspaceMembership.Role.AGENT)
        TeamMembership.objects.create(team=self.team_billing, user=self.agent_billing, role=TeamMembership.Role.MEMBER)

        self.mailbox = MailboxConnection.objects.create(
            workspace=self.workspace,
            email_address="support@shopease.com",
            provider=MailboxConnection.Provider.GMAIL,
            status=MailboxConnection.Status.ACTIVE
        )

    def test_inbound_email_triage_creates_proposal_and_customer(self):
        """Inbound email is saved, customer resolved, conversation linked, and proposal created."""
        email = InboundEmail.objects.create(
            workspace=self.workspace,
            mailbox_connection=self.mailbox,
            provider_message_id="gmail_msg_101",
            sender_email="customer1@example.com",
            sender_name="Alice Wonder",
            recipient="support@shopease.com",
            subject="Charged twice for Order #1002",
            normalized_text_body="My credit card was deducted twice for this order. Please help urgently.",
            received_at=timezone.now(),
        )

        proposal = email_triage_service.process_inbound_email(email)

        # 1. Customer created with normalized email
        customer = Customer.objects.get(workspace=self.workspace, normalized_email="customer1@example.com")
        self.assertEqual(customer.name, "Alice Wonder")
        self.assertEqual(email.linked_customer, customer)

        # 2. Critical triage classification
        self.assertEqual(proposal.ai_urgency, "CRITICAL")
        self.assertEqual(proposal.ai_intent, "PAYMENT_ISSUE")
        self.assertEqual(proposal.ai_sentiment, "ANGRY")
        self.assertEqual(proposal.approval_status, TicketProposal.ApprovalStatus.PENDING_REVIEW)
        self.assertEqual(proposal.ai_recommended_team, self.team_billing)

        # 3. Draft reply saved (not sent)
        self.assertTrue(len(proposal.ai_suggested_reply) > 20)

    def test_mandatory_team_assignment_during_approval(self):
        """Approving a ticket without selecting a team must fail."""
        email = InboundEmail.objects.create(
            workspace=self.workspace,
            mailbox_connection=self.mailbox,
            provider_message_id="gmail_msg_102",
            sender_email="customer2@example.com",
            subject="Need status on order",
            normalized_text_body="When will my package arrive?",
        )
        proposal = email_triage_service.process_inbound_email(email)

        self.client.login(username="manager@shopease.com", password=self.password)
        resp = self.client.post(f"/shopease/emails/proposals/{proposal.id}/action/", {
            "action": "approve",
            "assigned_team_id": ""  # Missing mandatory team!
        })
        self.assertEqual(resp.status_code, 302)

        # Proposal must remain pending review and NO ticket created
        proposal.refresh_from_db()
        self.assertEqual(proposal.approval_status, TicketProposal.ApprovalStatus.PENDING_REVIEW)
        self.assertIsNone(proposal.created_ticket)
        self.assertEqual(Ticket.objects.filter(workspace=self.workspace).count(), 0)

    def test_successful_approval_creates_ticket_and_assignment(self):
        """Valid approval with team creates Ticket, Assignment, Event, and links email."""
        email = InboundEmail.objects.create(
            workspace=self.workspace,
            mailbox_connection=self.mailbox,
            provider_message_id="gmail_msg_103",
            sender_email="customer3@example.com",
            subject="Double charge refund",
            normalized_text_body="Double charge on my account.",
        )
        proposal = email_triage_service.process_inbound_email(email)

        self.client.login(username="manager@shopease.com", password=self.password)
        resp = self.client.post(f"/shopease/emails/proposals/{proposal.id}/action/", {
            "action": "approve",
            "assigned_team_id": self.team_billing.id,
            "assigned_agent_id": self.agent_billing.id,
            "proposed_subject": "Refund Double Charge",
            "proposed_priority": "CRITICAL",
            "proposed_category": "Billing & Payments",
        })
        self.assertEqual(resp.status_code, 302)

        proposal.refresh_from_db()
        self.assertEqual(proposal.approval_status, TicketProposal.ApprovalStatus.APPROVED)
        self.assertIsNotNone(proposal.created_ticket)
        self.assertEqual(proposal.reviewed_by, self.manager)

        ticket = proposal.created_ticket
        self.assertEqual(ticket.subject, "Refund Double Charge")
        self.assertEqual(ticket.assigned_team, self.team_billing)
        self.assertEqual(ticket.assigned_agent, self.agent_billing)
        self.assertEqual(ticket.priority, Ticket.Priority.CRITICAL)

        # InboundEmail linked
        email.refresh_from_db()
        self.assertEqual(email.linked_ticket, ticket)
        self.assertEqual(email.processing_status, InboundEmail.ProcessingStatus.TICKET_APPROVED)

        # Assignment history recorded
        self.assertEqual(ticket.assignments.count(), 1)
        self.assertEqual(ticket.events.count(), 1)

    def test_proposal_rejection_does_not_create_ticket(self):
        """Rejecting proposal stores reason, creates no ticket, and preserves email."""
        email = InboundEmail.objects.create(
            workspace=self.workspace,
            mailbox_connection=self.mailbox,
            provider_message_id="gmail_msg_104",
            sender_email="spam@example.com",
            subject="Marketing spam",
            normalized_text_body="Buy cheap things here.",
        )
        proposal = email_triage_service.process_inbound_email(email)

        self.client.login(username="manager@shopease.com", password=self.password)
        resp = self.client.post(f"/shopease/emails/proposals/{proposal.id}/action/", {
            "action": "reject",
            "review_notes": "Spam promotional message, not a support inquiry."
        })
        self.assertEqual(resp.status_code, 302)

        proposal.refresh_from_db()
        self.assertEqual(proposal.approval_status, TicketProposal.ApprovalStatus.REJECTED)
        self.assertIsNone(proposal.created_ticket)
        self.assertEqual(proposal.review_notes, "Spam promotional message, not a support inquiry.")

        email.refresh_from_db()
        self.assertEqual(email.processing_status, InboundEmail.ProcessingStatus.REJECTED)
        self.assertEqual(Ticket.objects.filter(workspace=self.workspace).count(), 0)

    def test_prevent_duplicate_proposal_approval(self):
        """Approving an already approved proposal must not generate a second ticket."""
        email = InboundEmail.objects.create(
            workspace=self.workspace,
            mailbox_connection=self.mailbox,
            provider_message_id="gmail_msg_105",
            sender_email="customer5@example.com",
            subject="Order tracking question",
            normalized_text_body="Where is package?",
        )
        proposal = email_triage_service.process_inbound_email(email)

        self.client.login(username="manager@shopease.com", password=self.password)
        # First approval
        self.client.post(f"/shopease/emails/proposals/{proposal.id}/action/", {
            "action": "approve",
            "assigned_team_id": self.team_order.id,
        })
        self.assertEqual(Ticket.objects.filter(workspace=self.workspace).count(), 1)

        # Second approval attempt
        self.client.post(f"/shopease/emails/proposals/{proposal.id}/action/", {
            "action": "approve",
            "assigned_team_id": self.team_order.id,
        })
        # Must still be exactly 1 ticket
        self.assertEqual(Ticket.objects.filter(workspace=self.workspace).count(), 1)

