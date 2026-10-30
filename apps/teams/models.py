from django.conf import settings
from django.db import models
from django.utils.text import slugify
from apps.workspaces.models import Workspace

class Team(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="teams")
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=120)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("workspace", "slug")
        ordering = ["workspace", "name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.workspace.name} - {self.name}"

    @property
    def member_count(self) -> int:
        return self.memberships.count()


class TeamMembership(models.Model):
    class Role(models.TextChoices):
        LEAD = "LEAD", "Team Lead"
        MEMBER = "MEMBER", "Team Member"

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="team_memberships")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MEMBER)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("team", "user")
        ordering = ["team", "role", "created_at"]

    def __str__(self):
        return f"{self.user.email} in {self.team.name} ({self.role})"

