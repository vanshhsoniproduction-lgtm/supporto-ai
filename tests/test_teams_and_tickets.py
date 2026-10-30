from django.test import TestCase
from django.contrib.auth import get_user_model
from apps.workspaces.models import Workspace, WorkspaceMembership
from apps.teams.models import Team, TeamMembership
from apps.customers.models import Customer
from apps.tickets.models import Ticket
from apps.conversations.models import Conversation, Message
from services.tickets.ticket_service import ticket_service
from services.conversations.conversation_service import conversation_service

User = get_user_model()

class TeamsAndTicketsTests(TestCase):
    def setUp(self):
        self.workspace = Workspace.objects.create(name="ShopTest", slug="shoptest")

        self.agent_multi = User.objects.create_user(email="multi@shoptest.com", password="Pass123!")
        WorkspaceMembership.objects.create(workspace=self.workspace, user=self.agent_multi, role=WorkspaceMembership.Role.AGENT)

        self.team_order = Team.objects.create(workspace=self.workspace, name="Order Support", slug="order-support")
        self.team_billing = Team.objects.create(workspace=self.workspace, name="Billing Support", slug="billing-support")

        # Multi-team membership
        TeamMembership.objects.create(team=self.team_order, user=self.agent_multi, role=TeamMembership.Role.MEMBER)
        TeamMembership.objects.create(team=self.team_billing, user=self.agent_multi, role=TeamMembership.Role.MEMBER)

        self.customer = Customer.objects.create(workspace=self.workspace, name="Jane Doe", email="jane@example.com")

    def test_multi_team_membership(self):
        memberships = self.agent_multi.team_memberships.filter(team__workspace=self.workspace)
        self.assertEqual(memberships.count(), 2)
        team_names = set(memberships.values_list("team__name", flat=True))
        self.assertEqual(team_names, {"Order Support", "Billing Support"})

    def test_ticket_creation_and_assignment(self):
        ticket = Ticket.objects.create(
            workspace=self.workspace,
            customer=self.customer,
            subject="Damaged item received",
            description="Package was dented on arrival",
            priority=Ticket.Priority.MEDIUM,
            status=Ticket.Status.OPEN
        )
        self.assertTrue(ticket.ticket_number.startswith("TK-"))

        # Reassign to team and agent
        ticket_service.assign_ticket(
            ticket=ticket,
            new_team=self.team_order,
            new_agent=self.agent_multi,
            reason="Routing to Order specialist"
        )
        ticket.refresh_from_db()
        self.assertEqual(ticket.assigned_team, self.team_order)
        self.assertEqual(ticket.assigned_agent, self.agent_multi)
        self.assertEqual(ticket.assignments.count(), 1)

    def test_ticket_status_and_resolution(self):
        ticket = Ticket.objects.create(
            workspace=self.workspace,
            customer=self.customer,
            subject="Refund request",
            description="Refund requested",
            priority=Ticket.Priority.HIGH,
            status=Ticket.Status.OPEN
        )
        self.assertIsNone(ticket.resolved_at)

        ticket_service.update_status(ticket, Ticket.Status.RESOLVED, actor=self.agent_multi, comment="Refund processed.")
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.RESOLVED)
        self.assertIsNotNone(ticket.resolved_at)
        self.assertEqual(ticket.comments.count(), 1)

    def test_prevent_duplicate_ticket_generation(self):
        conv = Conversation.objects.create(
            workspace=self.workspace,
            customer=self.customer,
            channel=Conversation.Channel.WEB_CHAT,
            status=Conversation.Status.ACTIVE,
            intent="Billing Support",
            urgency=Conversation.Urgency.HIGH
        )
        Message.objects.create(conversation=conv, sender_type=Message.SenderType.CUSTOMER, content="I need a billing refund")

        # First finalization
        res1 = conversation_service.finalize_conversation(conv)
        self.assertIsNotNone(res1["ticket_number"])

        # Second finalization attempt
        res2 = conversation_service.finalize_conversation(conv)
        self.assertEqual(res1["ticket_number"], res2["ticket_number"])

        # Ensure only 1 ticket was created
        self.assertEqual(Ticket.objects.filter(conversation=conv).count(), 1)

