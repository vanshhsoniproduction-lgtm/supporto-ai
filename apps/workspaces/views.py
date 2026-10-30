from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.conf import settings
from django.http import HttpResponseForbidden
from apps.workspaces.models import WorkspaceSettings, WorkspaceMembership
from apps.tickets.models import Ticket
from apps.conversations.models import Conversation
from apps.teams.models import Team
from services.analytics.metrics_service import metrics_service
from services.workspaces.access_control import require_workspace_roles

def workspace_dashboard(request, company_slug):
    """
    Company-specific access point: /<company_slug>/
    - Unauthenticated: Displays company branding, welcome greeting, and ONLY 'Continue with Google' button.
      NO email/password form is displayed.
    - Authenticated: Displays the full Supporto AI workspace dashboard for authorized members.
      Unauthorized Google accounts are denied.
    """
    workspace = request.workspace

    # Handle unauthenticated visitors at /[company_slug]/
    if not request.user.is_authenticated:
        # Build Google OAuth link targeting this workspace
        google_login_url = f"/accounts/google/login/?workspace={workspace.slug}"
        welcome_message = getattr(workspace, "settings", None)
        welcome_text = welcome_message.welcome_message if welcome_message else "Welcome to Supporto AI Workspace"

        return render(request, "workspace/company_landing.html", {
            "workspace": workspace,
            "welcome_message": welcome_text,
            "google_login_url": google_login_url,
            "google_configured": bool(getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "")),
        })

    # User is authenticated - verify authorized membership
    membership = getattr(request, "membership", None)
    is_platform_admin = getattr(request.user, "is_platform_admin", False)

    if not membership and not is_platform_admin:
        # User is authenticated via Google or session, but not authorized for THIS workspace
        return render(request, "auth/unauthorized_workspace.html", {
            "workspace": workspace,
            "user_email": request.user.email,
        }, status=403)

    metrics = metrics_service.get_workspace_metrics(workspace)

    recent_tickets = Ticket.objects.filter(workspace=workspace).select_related(
        "customer", "assigned_team", "assigned_agent"
    ).order_by("-created_at")[:6]

    recent_conversations = Conversation.objects.filter(workspace=workspace).select_related(
        "customer"
    ).order_by("-created_at")[:6]

    return render(request, "workspace/dashboard.html", {
        "workspace": workspace,
        "metrics": metrics,
        "recent_tickets": recent_tickets,
        "recent_conversations": recent_conversations,
        "active_nav": "overview"
    })


@require_workspace_roles("OWNER", "ADMIN")
def workspace_settings_view(request, company_slug):
    workspace = request.workspace
    settings_obj, _ = WorkspaceSettings.objects.get_or_create(workspace=workspace)

    if request.method == "POST":
        workspace.name = request.POST.get("name", workspace.name).strip()
        workspace.description = request.POST.get("description", workspace.description).strip()
        workspace.save(update_fields=["name", "description", "updated_at"])

        settings_obj.company_website = request.POST.get("company_website", "").strip()
        settings_obj.support_email = request.POST.get("support_email", "").strip()
        settings_obj.welcome_message = request.POST.get("welcome_message", settings_obj.welcome_message).strip()
        settings_obj.sla_urgent_minutes = int(request.POST.get("sla_urgent_minutes", 30))
        settings_obj.sla_standard_hours = int(request.POST.get("sla_standard_hours", 24))
        settings_obj.ticket_auto_assignment = bool(request.POST.get("ticket_auto_assignment"))
        settings_obj.save()

        messages.success(request, "Company settings saved successfully.")
        return redirect("workspace_settings", company_slug=workspace.slug)

    return render(request, "workspace/settings.html", {
        "workspace": workspace,
        "settings": settings_obj,
        "active_nav": "company_settings"
    })
