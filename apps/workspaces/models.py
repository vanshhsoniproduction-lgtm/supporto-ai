import uuid
from django.conf import settings
from django.db import models
from django.utils.text import slugify
from django.utils import timezone

class Workspace(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending Approval"
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"

    class AuthPolicy(models.TextChoices):
        BOTH = "BOTH", "Email/Password and Google OAuth"
        PASSWORD = "PASSWORD", "Email and Password Only"
        GOOGLE = "GOOGLE", "Google OAuth Only"

    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=100, unique=True, db_index=True)
    logo = models.FileField(upload_to="workspaces/logos/", null=True, blank=True)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True
    )
    public_key = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        help_text="Secure public token for embedding customer chat widgets without exposing workspace ID"
    )
    allowed_auth_policy = models.CharField(
        max_length=20,
        choices=AuthPolicy.choices,
        default=AuthPolicy.BOTH
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.slug})"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.ACTIVE


class WorkspaceMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = "OWNER", "Workspace Owner"
        ADMIN = "ADMIN", "Administrator"
        MANAGER = "MANAGER", "Support Manager"
        AGENT = "AGENT", "Support Agent"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="workspace_memberships")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.AGENT)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("workspace", "user")
        ordering = ["workspace", "role", "created_at"]

    def __str__(self):
        return f"{self.user.email} - {self.workspace.name} ({self.role})"

    @property
    def is_admin_or_owner(self) -> bool:
        return self.role in (self.Role.OWNER, self.Role.ADMIN)


class WorkspaceSettings(models.Model):
    workspace = models.OneToOneField(Workspace, on_delete=models.CASCADE, related_name="settings")
    company_website = models.URLField(blank=True)
    support_email = models.EmailField(blank=True)
    ticket_auto_assignment = models.BooleanField(default=True)
    sla_urgent_minutes = models.PositiveIntegerField(default=30)
    sla_standard_hours = models.PositiveIntegerField(default=24)
    welcome_message = models.TextField(
        default="Hello! How can we help you today?",
        help_text="Default greeting shown in the customer chat widget"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Settings for {self.workspace.name}"


class WorkspaceAuthorizedEmail(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        AUTHORIZED = "AUTHORIZED", "Authorized"
        REVOKED = "REVOKED", "Revoked"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="authorized_emails")
    email = models.EmailField(max_length=255)
    normalized_email = models.EmailField(max_length=255, db_index=True)
    assigned_role = models.CharField(
        max_length=20,
        choices=WorkspaceMembership.Role.choices,
        default=WorkspaceMembership.Role.AGENT
    )
    assigned_teams = models.ManyToManyField(
        "teams.Team",
        blank=True,
        related_name="authorized_emails",
        help_text="Optional teams to automatically assign when user registers"
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.AUTHORIZED,
        db_index=True
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="authorized_email_invitations"
    )
    linked_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="authorized_email_records"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    authorized_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("workspace", "normalized_email")
        ordering = ["-created_at"]

    def clean(self):
        super().clean()
        if self.email:
            self.normalized_email = self.email.strip().lower()

    def save(self, *args, **kwargs):
        if self.email:
            self.normalized_email = self.email.strip().lower()
        if self.status == self.Status.AUTHORIZED and not self.authorized_at:
            self.authorized_at = timezone.now()
        elif self.status == self.Status.REVOKED and not self.revoked_at:
            self.revoked_at = timezone.now()
        super().save(*args, **kwargs)

    def revoke(self):
        self.status = self.Status.REVOKED
        self.revoked_at = timezone.now()
        self.save(update_fields=["status", "revoked_at"])

    def authorize(self):
        self.status = self.Status.AUTHORIZED
        self.authorized_at = timezone.now()
        self.revoked_at = None
        self.save(update_fields=["status", "authorized_at", "revoked_at"])

    def __str__(self):
        return f"{self.normalized_email} -> {self.workspace.name} ({self.assigned_role} - {self.status})"
