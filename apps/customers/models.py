import uuid
from django.db import models
from django.utils import timezone
from apps.workspaces.models import Workspace

class Customer(models.Model):
    class Source(models.TextChoices):
        EMAIL = "EMAIL", "Email"
        WIDGET = "WIDGET", "Chat Widget"
        VOICE = "VOICE", "Voice Call"
        MANUAL = "MANUAL", "Manual / Staff"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"
        BLOCKED = "BLOCKED", "Blocked"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="customers")
    name = models.CharField(max_length=150, default="Visitor")
    email = models.EmailField(blank=True, db_index=True)
    normalized_email = models.EmailField(blank=True, db_index=True)
    phone = models.CharField(max_length=30, blank=True)
    company = models.CharField(max_length=150, blank=True)
    source = models.CharField(max_length=30, choices=Source.choices, default=Source.WIDGET)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.ACTIVE)
    is_anonymous = models.BooleanField(default=True)
    session_token = models.CharField(max_length=100, db_index=True, blank=True)
    tags = models.JSONField(default=list, blank=True)
    internal_notes = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    first_seen = models.DateTimeField(default=timezone.now)
    last_seen = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self):
        super().clean()
        if self.email:
            self.normalized_email = self.email.strip().lower()

    def save(self, *args, **kwargs):
        if self.email:
            self.normalized_email = self.email.strip().lower()
            if self.is_anonymous and self.name != "Visitor":
                self.is_anonymous = False
        super().save(*args, **kwargs)

    @property
    def display_name(self) -> str:
        if self.name and self.name != "Visitor":
            return self.name
        return self.email or f"Customer #{self.pk}"

    def __str__(self):
        ident = self.email if self.email else (self.name if self.name else f"Customer #{self.pk}")
        return f"{ident} ({self.workspace.name})"
