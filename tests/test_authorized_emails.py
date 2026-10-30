from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from apps.workspaces.models import Workspace, WorkspaceMembership, WorkspaceAuthorizedEmail
from apps.teams.models import Team, TeamMembership

User = get_user_model()

class AuthorizedEmailsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.password = "SecPass123!"

        self.platform_admin = User.objects.create_superuser(
            email="superadmin@supporto.ai",
            password=self.password
        )

        self.ws_shopease = Workspace.objects.create(name="ShopEase", slug="shopease")
        self.ws_othercorp = Workspace.objects.create(name="OtherCorp", slug="othercorp")

        self.team_billing = Team.objects.create(workspace=self.ws_shopease, name="Billing Support", slug="billing-support")

    def test_platform_admin_can_authorize_email(self):
        """Platform admin authorizes an email address and assigns role and team."""
        self.client.login(username="superadmin@supporto.ai", password=self.password)
        resp = self.client.post(f"/admin/companies/{self.ws_shopease.slug}/authorized-emails/", {
            "action": "authorize",
            "email": "agent.smith@example.com",
            "assigned_role": "AGENT",
            "teams": [self.team_billing.id]
        })
        self.assertEqual(resp.status_code, 302)

        record = WorkspaceAuthorizedEmail.objects.get(workspace=self.ws_shopease, normalized_email="agent.smith@example.com")
        self.assertEqual(record.assigned_role, WorkspaceMembership.Role.AGENT)
        self.assertEqual(record.status, WorkspaceAuthorizedEmail.Status.AUTHORIZED)
        self.assertIn(self.team_billing, record.assigned_teams.all())

    def test_platform_admin_can_revoke_email(self):
        """Platform admin can revoke authorization."""
        record = WorkspaceAuthorizedEmail.objects.create(
            workspace=self.ws_shopease,
            email="revoke.me@example.com",
            normalized_email="revoke.me@example.com",
            assigned_role=WorkspaceMembership.Role.AGENT,
            status=WorkspaceAuthorizedEmail.Status.AUTHORIZED
        )
        self.client.login(username="superadmin@supporto.ai", password=self.password)
        resp = self.client.post(f"/admin/companies/{self.ws_shopease.slug}/authorized-emails/", {
            "action": "revoke",
            "record_id": record.id
        })
        self.assertEqual(resp.status_code, 302)
        record.refresh_from_db()
        self.assertEqual(record.status, WorkspaceAuthorizedEmail.Status.REVOKED)
        self.assertIsNotNone(record.revoked_at)

    def test_company_agent_cannot_access_platform_admin(self):
        """Company agent cannot access /admin/."""
        agent = User.objects.create_user(email="agent@shopease.com", password=self.password)
        WorkspaceMembership.objects.create(workspace=self.ws_shopease, user=agent, role=WorkspaceMembership.Role.AGENT)

        self.client.login(username="agent@shopease.com", password=self.password)
        resp = self.client.get("/admin/")
        self.assertEqual(resp.status_code, 403)

    def test_unauthorized_email_access_denied_with_exact_message(self):
        """Unauthorized Google email is denied with required message."""
        unauth_user = User.objects.create_user(email="unauthorized@gmail.com", password=self.password)
        self.client.login(username="unauthorized@gmail.com", password=self.password)
        resp = self.client.get("/shopease/")
        self.assertEqual(resp.status_code, 403)
        self.assertContains(resp, "This Google account has not been authorized for this workspace", status_code=403)

    def test_shopease_authorized_email_cannot_access_othercorp(self):
        """Authorization for ShopEase does not grant access to OtherCorp."""
        user = User.objects.create_user(email="shopease.staff@example.com", password=self.password)
        WorkspaceAuthorizedEmail.objects.create(
            workspace=self.ws_shopease,
            email="shopease.staff@example.com",
            normalized_email="shopease.staff@example.com",
            assigned_role=WorkspaceMembership.Role.AGENT,
            status=WorkspaceAuthorizedEmail.Status.AUTHORIZED,
            linked_user=user
        )
        WorkspaceMembership.objects.create(
            workspace=self.ws_shopease,
            user=user,
            role=WorkspaceMembership.Role.AGENT,
            is_active=True
        )

        self.client.login(username="shopease.staff@example.com", password=self.password)
        # ShopEase access succeeds
        resp_a = self.client.get("/shopease/")
        self.assertEqual(resp_a.status_code, 200)

        # OtherCorp access denied
        resp_b = self.client.get("/othercorp/")
        self.assertEqual(resp_b.status_code, 403)

