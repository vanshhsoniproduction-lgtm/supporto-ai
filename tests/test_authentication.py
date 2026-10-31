from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from apps.workspaces.models import Workspace, WorkspaceMembership, WorkspaceAuthorizedEmail

User = get_user_model()

class AuthenticationArchitectureTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.password = "ValidPassword123!"

        self.workspace_a = Workspace.objects.create(name="ShopEase", slug="shopease")
        self.workspace_b = Workspace.objects.create(name="OtherCorp", slug="othercorp")

        self.platform_admin = User.objects.create_superuser(
            email="admin@supporto.ai",
            password=self.password
        )

        self.staff_email = "sarah.connor@example.com"
        self.staff_user = User.objects.create_user(
            email=self.staff_email,
            password=self.password,
            first_name="Sarah",
            last_name="Connor"
        )

        # Pre-authorize Sarah for ShopEase
        self.auth_record = WorkspaceAuthorizedEmail.objects.create(
            workspace=self.workspace_a,
            email=self.staff_email,
            normalized_email=self.staff_email,
            assigned_role=WorkspaceMembership.Role.AGENT,
            status=WorkspaceAuthorizedEmail.Status.AUTHORIZED,
            linked_user=self.staff_user,
        )

    def test_unauthenticated_platform_admin_redirects_to_admin_login(self):
        """Unauthenticated /admin/ access must redirect to /admin/login/, not /login/."""
        resp = self.client.get("/admin/")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith("/admin/login/"))

    def test_authorized_platform_admin_can_access_admin(self):
        """Authorized platform admin can access /admin/."""
        self.client.login(username="admin@supporto.ai", password=self.password)
        resp = self.client.get("/admin/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Platform Overview")

    def test_company_slug_shows_google_login_only_when_unauthenticated(self):
        """Company slug page must show Google login button and NO password form."""
        resp = self.client.get("/shopease/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Continue with Google")
        self.assertNotContains(resp, 'type="password"')
        self.assertNotContains(resp, "name=\"password\"")

    def test_unauthorized_google_email_denied(self):
        """An authenticated Google email not on the authorized list is denied entry."""
        unauthorized_email = "unauthorized.stranger@gmail.com"
        unauth_user = User.objects.create_user(
            email=unauthorized_email,
            password=self.password,
            first_name="Stranger"
        )
        self.client.login(username=unauthorized_email, password=self.password)
        resp = self.client.get("/shopease/")
        self.assertEqual(resp.status_code, 403)
        self.assertContains(resp, "This Google account has not been authorized for this workspace", status_code=403)

    def test_authorized_google_email_enters_workspace(self):
        """Authorized Google email enters the workspace dashboard."""
        WorkspaceMembership.objects.create(
            workspace=self.workspace_a,
            user=self.staff_user,
            role=WorkspaceMembership.Role.AGENT,
            is_active=True
        )
        self.client.login(username=self.staff_email, password=self.password)
        resp = self.client.get("/shopease/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "ShopEase")

    def test_user_authorized_for_shopease_cannot_access_other_company(self):
        """An authorized user of ShopEase cannot enter OtherCorp."""
        WorkspaceMembership.objects.create(
            workspace=self.workspace_a,
            user=self.staff_user,
            role=WorkspaceMembership.Role.AGENT,
            is_active=True
        )
        self.client.login(username=self.staff_email, password=self.password)
        resp = self.client.get("/othercorp/")
        self.assertEqual(resp.status_code, 403)

    def test_revoked_authorization_denies_entry(self):
        """Revoking an authorization prevents access."""
        self.auth_record.revoke()
        self.client.login(username=self.staff_email, password=self.password)
        resp = self.client.get("/shopease/")
        self.assertEqual(resp.status_code, 403)

    def test_logout_redirects_to_landing(self):
        """Logout signs out the session and redirects to public landing page."""
        self.client.login(username=self.staff_email, password=self.password)
        resp = self.client.post("/logout/")
        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(resp, "/")

    def test_multi_workspace_selection_page(self):
        """A user linked to multiple workspaces sees the workspace switcher listing all organizations."""
        WorkspaceMembership.objects.create(
            workspace=self.workspace_a,
            user=self.staff_user,
            role=WorkspaceMembership.Role.OWNER,
            is_active=True
        )
        WorkspaceMembership.objects.create(
            workspace=self.workspace_b,
            user=self.staff_user,
            role=WorkspaceMembership.Role.AGENT,
            is_active=True
        )
        self.client.login(username=self.staff_email, password=self.password)
        resp = self.client.get("/select-workspace/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Select Company Workspace")
        self.assertContains(resp, "ShopEase")
        self.assertContains(resp, "OtherCorp")
        self.assertContains(resp, "/shopease/")
        self.assertContains(resp, "/othercorp/")
