from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.views.decorators.http import require_POST
from django.utils.text import slugify
from apps.workspaces.models import Workspace, WorkspaceMembership, WorkspaceSettings
from apps.ai_engine.models import AgentConfiguration
from apps.voice_support.models import VoiceConfiguration
from apps.analytics.models import AuditLog
from services.workspaces.access_control import require_platform_admin
from services.analytics.metrics_service import metrics_service
from services.ai.model_manager import model_manager

User = get_user_model()

@require_platform_admin
def platform_admin_overview(request):
    metrics = metrics_service.get_platform_metrics()
    recent_workspaces = Workspace.objects.all().order_by("-created_at")[:5]
    recent_logs = AuditLog.objects.all().order_by("-created_at")[:10]
    return render(request, "platform_admin/overview.html", {
        "metrics": metrics,
        "recent_workspaces": recent_workspaces,
        "recent_logs": recent_logs,
        "active_tab": "overview"
    })


@require_platform_admin
def platform_admin_companies(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        slug = slugify(request.POST.get("slug", "").strip() or name)
        description = request.POST.get("description", "").strip()
        owner_email = request.POST.get("owner_email", "").strip().lower()

        if not name or not slug:
            messages.error(request, "Company name and slug are required.")
            return redirect("platform_admin_companies")

        if Workspace.objects.filter(slug=slug).exists():
            messages.error(request, f"Company slug '{slug}' is already taken. Please choose another.")
            return redirect("platform_admin_companies")

        workspace = Workspace.objects.create(
            name=name,
            slug=slug,
            description=description,
            status=Workspace.Status.ACTIVE
        )
        # Create default settings, AI agent config, and voice config
        WorkspaceSettings.objects.create(workspace=workspace)
        AgentConfiguration.objects.create(workspace=workspace)
        VoiceConfiguration.objects.create(workspace=workspace)

        # Assign owner if email specified
        if owner_email:
            owner, created = User.objects.get_or_create(
                email=owner_email,
                defaults={"username": owner_email, "first_name": name, "last_name": "Admin"}
            )
            if created:
                owner.set_password("Supporto@123")
                owner.save()
            WorkspaceMembership.objects.create(
                workspace=workspace,
                user=owner,
                role=WorkspaceMembership.Role.OWNER
            )

        AuditLog.objects.create(
            workspace=workspace,
            actor=request.user,
            action="WORKSPACE_CREATED",
            resource_type="Workspace",
            resource_id=str(workspace.id),
            details={"name": workspace.name, "slug": workspace.slug, "owner": owner_email}
        )
        messages.success(request, f"Company '{workspace.name}' successfully created!")
        return redirect("platform_admin_companies")

    workspaces = Workspace.objects.all().prefetch_related("memberships__user")
    return render(request, "platform_admin/companies.html", {
        "workspaces": workspaces,
        "active_tab": "companies"
    })


@require_platform_admin
@require_POST
def platform_admin_company_toggle(request, workspace_id):
    workspace = get_object_or_404(Workspace, id=workspace_id)
    if workspace.status == Workspace.Status.ACTIVE:
        workspace.status = Workspace.Status.SUSPENDED
        action = "WORKSPACE_SUSPENDED"
    else:
        workspace.status = Workspace.Status.ACTIVE
        action = "WORKSPACE_ACTIVATED"

    workspace.save(update_fields=["status", "updated_at"])
    AuditLog.objects.create(
        workspace=workspace,
        actor=request.user,
        action=action,
        resource_type="Workspace",
        resource_id=str(workspace.id)
    )
    messages.success(request, f"Workspace '{workspace.name}' status updated to {workspace.status}.")
    return redirect("platform_admin_companies")


@require_platform_admin
def platform_admin_users(request):
    users = User.objects.all().prefetch_related("workspace_memberships__workspace").order_by("-date_joined")
    return render(request, "platform_admin/users.html", {
        "users": users,
        "active_tab": "users"
    })


@require_platform_admin
def platform_admin_ai_models(request):
    health = model_manager.get_health_status()
    return render(request, "platform_admin/ai_models.html", {
        "health": health,
        "active_tab": "ai_models"
    })


@require_platform_admin
def platform_admin_activity(request):
    logs = AuditLog.objects.all().select_related("actor", "workspace").order_by("-created_at")[:100]
    return render(request, "platform_admin/activity.html", {
        "logs": logs,
        "active_tab": "activity"
    })

