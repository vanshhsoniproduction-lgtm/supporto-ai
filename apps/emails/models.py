from django.conf import settings
from django.db import models
from django.utils import timezone
from apps.workspaces.models import Workspace
from apps.tickets.models import Ticket

class MailboxConnection(models.Model):
    class Provider(models.TextChoices):
        GMAIL = "GMAIL", "Google Gmail API"
        OUTLOOK = "OUTLOOK", "Microsoft Graph / Outlook (Future)"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        ERROR = "ERROR", "Connection Error"
        DISCONNECTED = "DISCONNECTED", "Disconnected"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="mailbox_connections")
    provider = models.CharField(max_length=40, choices=Provider.choices, default=Provider.GMAIL)
    email_address = models.EmailField(db_index=True)
    provider_account_id = models.CharField(max_length=255, blank=True)
    encrypted_access_token = models.TextField(blank=True)
    encrypted_refresh_token = models.TextField(blank=True)
    token_expiry = models.DateTimeField(null=True, blank=True)
    granted_scopes = models.TextField(blank=True)
    sync_cursor = models.CharField(max_length=255, blank=True, help_text="Gmail historyId or delta link")
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_successful_sync_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("workspace", "email_address")

    def __str__(self):
        return f"{self.email_address} ({self.workspace.name}) - {self.status}"


class InboundEmail(models.Model):
    class ProcessingStatus(models.TextChoices):
        NEW = "NEW", "New"
        PROCESSING = "PROCESSING", "Processing"
        ANALYZED = "ANALYZED", "Analyzed"
        TICKET_PROPOSED = "TICKET_PROPOSED", "Ticket Proposed (Pending Review)"
        TICKET_APPROVED = "TICKET_APPROVED", "Ticket Approved"
        NO_TICKET = "NO_TICKET", "No Ticket Required"
        REJECTED = "REJECTED", "Proposal Rejected"
        FAILED = "FAILED", "Processing Failed"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="inbound_emails")
    mailbox_connection = models.ForeignKey(
        MailboxConnection,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emails"
    )
    provider_message_id = models.CharField(max_length=255, db_index=True)
    provider_thread_id = models.CharField(max_length=255, blank=True)
    sender_email = models.EmailField(db_index=True)
    sender_name = models.CharField(max_length=255, blank=True)
    recipient = models.EmailField(blank=True)
    cc = models.TextField(blank=True)
    subject = models.CharField(max_length=500)
    original_text_body = models.TextField(blank=True)
    normalized_text_body = models.TextField(blank=True)
    html_body = models.TextField(blank=True)
    received_at = models.DateTimeField(default=timezone.now)
    attachments_metadata = models.JSONField(default=list, blank=True)
    processing_status = models.CharField(
        max_length=30,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.NEW,
        db_index=True
    )
    linked_customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inbound_emails"
    )
    linked_conversation = models.ForeignKey(
        "conversations.Conversation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inbound_emails"
    )
    linked_ticket = models.ForeignKey(
        "tickets.Ticket",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inbound_emails"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_at"]
        unique_together = ("workspace", "provider_message_id")

    def __str__(self):
        return f"[{self.workspace.slug}] {self.subject[:40]} from {self.sender_email}"


class TicketProposal(models.Model):
    class ApprovalStatus(models.TextChoices):
        PENDING_REVIEW = "PENDING_REVIEW", "Pending Review"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        NEEDS_MORE_INFORMATION = "NEEDS_MORE_INFORMATION", "Needs More Information"
        NO_TICKET_REQUIRED = "NO_TICKET_REQUIRED", "No Ticket Required"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="ticket_proposals")
    inbound_email = models.OneToOneField(InboundEmail, on_delete=models.CASCADE, related_name="proposal")
    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="ticket_proposals")
    conversation = models.ForeignKey(
        "conversations.Conversation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_proposals"
    )
    proposed_subject = models.CharField(max_length=255)
    proposed_description = models.TextField()
    proposed_category = models.CharField(max_length=100, default="General Support")
    proposed_priority = models.CharField(
        max_length=20,
        choices=Ticket.Priority.choices,
        default=Ticket.Priority.MEDIUM
    )
    ai_intent = models.CharField(max_length=100, blank=True)
    ai_sentiment = models.CharField(max_length=30, blank=True)
    ai_urgency = models.CharField(max_length=30, blank=True)
    ai_summary = models.TextField(blank=True)
    ai_recommended_team = models.ForeignKey("teams.Team", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    ai_confidence = models.FloatField(default=0.0)
    ai_suggested_reply = models.TextField(blank=True)
    edited_suggested_reply = models.TextField(blank=True)
    kb_sources_used = models.JSONField(default=list, blank=True)
    approval_status = models.CharField(
        max_length=30,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING_REVIEW,
        db_index=True
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_proposals"
    )
    review_notes = models.TextField(blank=True)
    created_ticket = models.OneToOneField(
        "tickets.Ticket",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proposal"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Proposal #{self.id} for {self.inbound_email.subject[:30]} ({self.approval_status})"
