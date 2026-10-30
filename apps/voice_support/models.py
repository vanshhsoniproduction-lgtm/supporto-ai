from django.db import models
from apps.workspaces.models import Workspace
from apps.conversations.models import Conversation
from apps.teams.models import Team

class VoiceConfiguration(models.Model):
    workspace = models.OneToOneField(Workspace, on_delete=models.CASCADE, related_name="voice_config")
    is_enabled = models.BooleanField(default=True)
    voice_name = models.CharField(max_length=50, default="af_sarah", help_text="Kokoro voice identifier")
    speed = models.FloatField(default=1.0)
    welcome_voice_text = models.TextField(
        default="Welcome to customer support. How may we assist you today?",
        help_text="Spoken audio greeting when voice call opens"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Voice Config for {self.workspace.name}"


class VoiceSession(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="voice_sessions")
    conversation = models.OneToOneField(Conversation, on_delete=models.CASCADE, related_name="voice_session")
    audio_seconds = models.FloatField(default=0.0)
    client_ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"VoiceSession #{self.id} for Conv #{self.conversation_id}"


class IVRMenu(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="ivr_menus")
    name = models.CharField(max_length=100, default="Main Support Menu")
    greeting_text = models.TextField(default="Press 1 for Order Support. Press 2 for Billing Support. Press 3 to speak with AI.")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.workspace.name} - {self.name}"


class IVROption(models.Model):
    class ActionType(models.TextChoices):
        ROUTE_TEAM = "ROUTE_TEAM", "Route to Team Queue"
        ROUTE_AI = "ROUTE_AI", "Connect to AI Assistant"
        MESSAGE = "MESSAGE", "Play Audio Information"

    menu = models.ForeignKey(IVRMenu, on_delete=models.CASCADE, related_name="options")
    digit = models.PositiveSmallIntegerField()
    label = models.CharField(max_length=100)
    action_type = models.CharField(max_length=30, choices=ActionType.choices, default=ActionType.ROUTE_AI)
    target_team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True)
    response_text = models.TextField(blank=True)

    class Meta:
        unique_together = ("menu", "digit")
        ordering = ["digit"]

    def __str__(self):
        return f"Key {self.digit}: {self.label}"

