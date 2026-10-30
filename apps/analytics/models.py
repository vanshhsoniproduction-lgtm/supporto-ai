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

