from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from apps.workspaces.models import Workspace, WorkspaceMembership
from apps.customers.models import Customer
from apps.tickets.models import Ticket
from apps.conversations.models import Conversation
from apps.knowledge_base.models import KnowledgeDocument
from services.ai.rag_service import rag_service

User = get_user_model()

class WorkspaceSecurityTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.password = "SecPass123!"

        # Create two separate tenants
        self.ws_a = Workspace.objects.create(name="Company A", slug="comp-a")
        self.ws_b = Workspace.objects.create(name="Company B", slug="comp-b")

        # User A belongs only to Company A
        self.user_a = User.objects.create_user(email="user_a@compa.com", password=self.password)
        WorkspaceMembership.objects.create(workspace=self.ws_a, user=self.user_a, role=WorkspaceMembership.Role.AGENT)

        # User B belongs only to Company B
        self.user_b = User.objects.create_user(email="user_b@compb.com", password=self.password)
        WorkspaceMembership.objects.create(workspace=self.ws_b, user=self.user_b, role=WorkspaceMembership.Role.AGENT)

        # Resources in Company B
        self.cust_b = Customer.objects.create(workspace=self.ws_b, name="Customer B", email="custb@example.com")
        self.ticket_b = Ticket.objects.create(
            workspace=self.ws_b,
            customer=self.cust_b,
            ticket_number="TK-B-001",
            subject="Confidential Bug in Company B",
            description="Company B proprietary secrets",
            status=Ticket.Status.OPEN
        )
        self.doc_b = KnowledgeDocument.objects.create(
            workspace=self.ws_b,
            title="Company B Trade Secrets",
            content="Top secret algorithm",
            is_active=True
        )

    def test_cross_workspace_portal_access_denied(self):
        """User A attempts to access Company B portal by changing URL slug."""
        self.client.login(username="user_a@compa.com", password=self.password)
        resp = self.client.get(f"/{self.ws_b.slug}/")
        self.assertEqual(resp.status_code, 403)
        self.assertContains(resp, "Access Denied", status_code=403)

    def test_cross_workspace_ticket_access_denied(self):
        """User A attempts to access Company B ticket by ticket number under company A."""
        self.client.login(username="user_a@compa.com", password=self.password)
        resp = self.client.get(f"/{self.ws_a.slug}/tickets/{self.ticket_b.ticket_number}/")
        # Should return 404 because ticket does not belong to Company A
        self.assertEqual(resp.status_code, 404)

    def test_cross_workspace_rag_isolation(self):
        """RAG service must never retrieve documents from other companies."""
        # Query Company A using Company B's keywords
        results_a = rag_service.retrieve_context(workspace_id=self.ws_a.id, query="Trade Secrets algorithm")
        self.assertEqual(len(results_a), 0)

        # Query Company B
        results_b = rag_service.retrieve_context(workspace_id=self.ws_b.id, query="Trade Secrets algorithm")
        self.assertGreater(len(results_b), 0)
        self.assertEqual(results_b[0]["title"], "Company B Trade Secrets")

    def test_invalid_workspace_slug_returns_404(self):
        self.client.login(username="user_a@compa.com", password=self.password)
        resp = self.client.get("/nonexistent-company-slug-xyz/")
        self.assertEqual(resp.status_code, 404)

    def test_unauthorized_role_escalation_denied(self):
        """Agent in Company A cannot access Owner/Admin settings."""
        self.client.login(username="user_a@compa.com", password=self.password)
        resp = self.client.get(f"/{self.ws_a.slug}/settings/")
        self.assertEqual(resp.status_code, 403)

