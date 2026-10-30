import uuid
from django.db import models
from apps.workspaces.models import Workspace

class Customer(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="customers")
    name = models.CharField(max_length=150, default="Visitor")
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    is_anonymous = models.BooleanField(default=True)
    session_token = models.CharField(max_length=100, db_index=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        ident = self.email if self.email else (self.name if self.name else f"Customer #{self.pk}")
        return f"{ident} ({self.workspace.name})"

