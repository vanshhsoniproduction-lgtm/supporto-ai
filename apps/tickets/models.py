from django.conf import settings
from django.db import models
from django.utils import timezone
from apps.workspaces.models import Workspace
from apps.customers.models import Customer
from apps.teams.models import Team
from apps.conversations.models import Conversation

class Ticket(models.Model):
    class Priority(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"
        CRITICAL = "CRITICAL", "Critical"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        PENDING = "PENDING", "Pending Customer"
        RESOLVED = "RESOLVED", "Resolved"
        CLOSED = "CLOSED", "Closed"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="tickets")
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="tickets")
    conversation = models.OneToOneField(
        Conversation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket"
    )
    ticket_number = models.CharField(max_length=32, unique=True, db_index=True)
    subject = models.CharField(max_length=255)
    description = models.TextField()
    category = models.CharField(max_length=100, default="General Support")
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.MEDIUM, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN, db_index=True)
    assigned_team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tickets"
    )
    assigned_agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tickets"
    )
    escalation_reason = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.ticket_number}] {self.subject} ({self.status})"

    def save(self, *args, **kwargs):
        if not self.ticket_number:
            prefix = "TK"
            rand_id = timezone.now().strftime("%y%m%d%H%M%S")
            self.ticket_number = f"{prefix}-{rand_id}"
        if self.status in (self.Status.RESOLVED, self.Status.CLOSED) and not self.resolved_at:
            self.resolved_at = timezone.now()
        super().save(*args, **kwargs)


class TicketAssignment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="assignments")
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="made_assignments"
    )
    previous_team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    new_team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    previous_agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+"
    )
    new_agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+"
    )
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class TicketComment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    is_internal = models.BooleanField(
        default=False,
        help_text="If True, only visible to staff/agents. If False, visible to customer."
    )
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        note = "Internal" if self.is_internal else "Reply"
        return f"[{note}] {self.content[:30]}"


class TicketEvent(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    event_type = models.CharField(max_length=60)
    description = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

