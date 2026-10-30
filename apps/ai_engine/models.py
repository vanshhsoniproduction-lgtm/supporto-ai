from django.db import models
from apps.workspaces.models import Workspace
from apps.conversations.models import Conversation
from apps.tickets.models import Ticket

class AgentConfiguration(models.Model):
    workspace = models.OneToOneField(Workspace, on_delete=models.CASCADE, related_name="agent_config")
    system_prompt = models.TextField(
        default="You are Supporto AI, an empathetic, concise, and helpful customer support agent. "
                "Answer customer queries strictly based on the company's knowledge base. "
                "If you cannot find the answer or if the issue involves urgent billing/account problems, escalate to human support."
    )
    confidence_threshold = models.FloatField(default=0.7)
    auto_escalate_urgent = models.BooleanField(default=True)
    temperature = models.FloatField(default=0.2)
    max_tokens = models.PositiveIntegerField(default=512)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"AI Agent Config for {self.workspace.name}"


class AgentRun(models.Model):
    class RunType(models.TextChoices):
        CHAT = "CHAT", "Customer Response Generation"
        CLASSIFY = "CLASSIFY", "Intent & Urgency Classification"
        SUMMARIZE = "SUMMARIZE", "Ticket / Conversation Summarization"
        ROUTE = "ROUTE", "Team Routing Recommendation"
        TOOL = "TOOL", "Tool Execution Loop"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="agent_runs")
    conversation = models.ForeignKey(Conversation, on_delete=models.SET_NULL, null=True, blank=True, related_name="agent_runs")
    ticket = models.ForeignKey(Ticket, on_delete=models.SET_NULL, null=True, blank=True, related_name="agent_runs")
    run_type = models.CharField(max_length=30, choices=RunType.choices, default=RunType.CHAT)
    input_prompt = models.TextField()
    output_response = models.TextField(blank=True)
    tokens_used = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    success = models.BooleanField(default=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.run_type}] Run #{self.id} for {self.workspace.name}"


class ToolExecution(models.Model):
    agent_run = models.ForeignKey(AgentRun, on_delete=models.CASCADE, related_name="tool_executions")
    tool_name = models.CharField(max_length=100)
    arguments = models.JSONField(default=dict)
    result = models.JSONField(default=dict)
    is_success = models.BooleanField(default=True)
    executed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["executed_at"]

    def __str__(self):
        return f"Tool {self.tool_name} ({'Success' if self.is_success else 'Failed'})"


class ResponseFeedback(models.Model):
    agent_run = models.ForeignKey(AgentRun, on_delete=models.CASCADE, related_name="feedbacks")
    rating = models.IntegerField(choices=[(1, "1 Star"), (2, "2 Stars"), (3, "3 Stars"), (4, "4 Stars"), (5, "5 Stars")])
    feedback_text = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Rating {self.rating} for Run #{self.agent_run_id}"

