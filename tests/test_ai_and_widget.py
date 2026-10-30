from django.test import TestCase, Client
from apps.workspaces.models import Workspace
from apps.teams.models import Team
from apps.tickets.models import Ticket
from apps.conversations.models import Conversation
from apps.customers.models import Customer
from services.ai.model_manager import model_manager
from services.ai.tool_registry import tool_registry

class AIAndWidgetTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.workspace = Workspace.objects.create(name="WidgetTest", slug="widgettest")
        self.billing_team = Team.objects.create(workspace=self.workspace, name="Billing Support", slug="billing-support")

    def test_model_paths_and_health(self):
        health = model_manager.get_health_status()
        self.assertIn("llm", health)
        self.assertIn("stt", health)
        self.assertIn("tts", health)
        self.assertTrue(health["ai_enabled"])

    def test_tool_registry_ticket_creation(self):
        cust = Customer.objects.create(workspace=self.workspace, name="Bob Tester")
        result = tool_registry.create_ticket(
            workspace_id=self.workspace.id,
            customer_id=cust.id,
            subject="Tool created ticket",
            description="Created via AI tool execution",
            priority="HIGH"
        )
        self.assertTrue(result["success"])
        self.assertIn("ticket_number", result)
        self.assertEqual(Ticket.objects.filter(workspace=self.workspace).count(), 1)

    def test_immediate_urgent_escalation_via_tool(self):
        cust = Customer.objects.create(workspace=self.workspace, name="Bob Tester")
        conv = Conversation.objects.create(workspace=self.workspace, customer=cust, channel=Conversation.Channel.WEB_CHAT)

        result = tool_registry.escalate_to_human(
            workspace_id=self.workspace.id,
            conversation_id=conv.id,
            reason="Customer reported double billing"
        )
        self.assertTrue(result["success"])
        self.assertTrue(result["escalated"])
        self.assertEqual(result["priority"], "CRITICAL")

        conv.refresh_from_db()
        self.assertTrue(conv.is_escalated)
        self.assertEqual(conv.urgency, "CRITICAL")

    def test_widget_message_flow_and_urgent_detection(self):
        # Post customer message with urgent keyword
        resp = self.client.post(
            f"/widget/{self.workspace.public_key}/message/",
            data='{"message": "I was deducted twice for my order!", "customer_name": "Urgent User"}',
            content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("ai_message", data)
        self.assertTrue(data.get("is_escalated"))
        self.assertIsNotNone(data.get("escalation_ticket"))
        self.assertEqual(data.get("urgency"), "CRITICAL")

        # Verify ticket was generated and assigned to Billing Support
        ticket = Ticket.objects.get(ticket_number=data["escalation_ticket"])
        self.assertEqual(ticket.priority, Ticket.Priority.CRITICAL)
        self.assertEqual(ticket.assigned_team, self.billing_team)

