from django.db import models
from apps.workspaces.models import Workspace
from apps.customers.models import Customer

class Conversation(models.Model):
    class Channel(models.TextChoices):
        WEB_CHAT = "WEB_CHAT", "Web Chat Widget"
        BROWSER_VOICE = "BROWSER_VOICE", "Browser Voice Call"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        COMPLETED = "COMPLETED", "Completed"
        ABANDONED = "ABANDONED", "Abandoned"

    class Sentiment(models.TextChoices):
        POSITIVE = "POSITIVE", "Positive"
        NEUTRAL = "NEUTRAL", "Neutral"
        NEGATIVE = "NEGATIVE", "Negative"
        FRUSTRATED = "FRUSTRATED", "Frustrated"

    class Urgency(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"
        CRITICAL = "CRITICAL", "Critical"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="conversations")
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="conversations")
    channel = models.CharField(max_length=30, choices=Channel.choices, default=Channel.WEB_CHAT)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    summary = models.TextField(blank=True)
    intent = models.CharField(max_length=120, blank=True)
    sentiment = models.CharField(max_length=30, choices=Sentiment.choices, default=Sentiment.NEUTRAL)
    urgency = models.CharField(max_length=30, choices=Urgency.choices, default=Urgency.LOW)
    is_escalated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Conv #{self.id} [{self.channel}] - {self.workspace.name} ({self.status})"

    @property
    def message_count(self) -> int:
        return self.messages.count()


class Message(models.Model):
    class SenderType(models.TextChoices):
        CUSTOMER = "CUSTOMER", "Customer"
        AI = "AI", "Supporto AI"
        AGENT = "AGENT", "Human Support Agent"
        SYSTEM = "SYSTEM", "System"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    sender_type = models.CharField(max_length=20, choices=SenderType.choices)
    content = models.TextField()
    audio_file = models.FileField(upload_to="audio/", null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.sender_type}: {self.content[:40]}"

