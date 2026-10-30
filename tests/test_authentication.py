from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from apps.workspaces.models import Workspace, WorkspaceMembership

User = get_user_model()

class AuthenticationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.password = "ValidPassword123!"

        self.user = User.objects.create_user(
            email="user@test.com",
            password=self.password,
            first_name="Test",
            last_name="User"
        )
        self.platform_admin = User.objects.create_superuser(
            email="admin@test.com",
            password=self.password
        )
        self.inactive_user = User.objects.create_user(
            email="inactive@test.com",
            password=self.password,
            is_active=False
        )

        self.workspace = Workspace.objects.create(name="Acme", slug="acme")
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=self.user,
            role=WorkspaceMembership.Role.AGENT
        )

    def test_successful_login(self):
        resp = self.client.post("/login/", {
            "email": "user@test.com",
            "password": self.password
        })
        self.assertEqual(resp.status_code, 302)
        # Should redirect to login_redirect then to workspace dashboard
        follow_resp = self.client.get(resp.url)
        self.assertEqual(follow_resp.status_code, 302)
        self.assertIn("/acme/", follow_resp.url)

    def test_invalid_login(self):
        resp = self.client.post("/login/", {
            "email": "user@test.com",
            "password": "WrongPassword"
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Invalid email or password")

    def test_inactive_user_login(self):
        resp = self.client.post("/login/", {
            "email": "inactive@test.com",
            "password": self.password
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Invalid email or password")

    def test_logout(self):
        self.client.login(username="user@test.com", password=self.password)
        resp = self.client.post("/logout/")
        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(resp, "/login/")

    def test_unauthorized_platform_admin_access(self):
        # Regular user logged in
        self.client.login(username="user@test.com", password=self.password)
        resp = self.client.get("/admin/")
        # Should be forbidden or permission denied (403)
        self.assertEqual(resp.status_code, 403)

    def test_authorized_platform_admin_access(self):
        self.client.login(username="admin@test.com", password=self.password)
        resp = self.client.get("/admin/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Platform Overview")

