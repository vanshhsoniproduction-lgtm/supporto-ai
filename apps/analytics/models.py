from django.conf import settings
from django.db import models
from apps.workspaces.models import Workspace

class AuditLog(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, null=True, blank=True, related_name="audit_logs")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_actions")
    action = models.CharField(max_length=100, db_index=True)
    resource_type = models.CharField(max_length=60, db_index=True)
    resource_id = models.CharField(max_length=64, blank=True)
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        actor_name = self.actor.email if self.actor else "System"
        return f"[{self.action}] by {actor_name} on {self.resource_type}:{self.resource_id}"


class SentimentLog(models.Model):
    class Channel(models.TextChoices):
        EMAIL = "EMAIL", "Incoming Email"
        WEB_CHAT = "WEB_CHAT", "Website Chat Widget"
        BROWSER_VOICE = "BROWSER_VOICE", "Browser Voice Conversation"

    class Sentiment(models.TextChoices):
        POSITIVE = "POSITIVE", "Positive"
        NEUTRAL = "NEUTRAL", "Neutral"
        NEGATIVE = "NEGATIVE", "Negative"
        ANGRY = "ANGRY", "Angry"
        FRUSTRATED = "FRUSTRATED", "Frustrated"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="sentiment_logs")
    channel = models.CharField(max_length=30, choices=Channel.choices)
    sentiment = models.CharField(max_length=30, choices=Sentiment.choices)
    confidence = models.FloatField(default=0.85)
    source_reference = models.CharField(max_length=120, blank=True)
    snippet = models.TextField(blank=True)
    model_source = models.CharField(max_length=60, default="supporto_ai_engine")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.workspace.slug}][{self.channel}] {self.sentiment} ({self.confidence:.2f})"
