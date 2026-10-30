from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.http import HttpResponseForbidden
from apps.workspaces.models import WorkspaceSettings, WorkspaceMembership
from apps.tickets.models import Ticket
from apps.conversations.models import Conversation
from apps.teams.models import Team
from services.analytics.metrics_service import metrics_service
from services.workspaces.access_control import require_workspace_roles

def workspace_dashboard(request, company_slug):
    workspace = request.workspace

    # Handle unauthenticated visitors at /[company_slug]/
    if not request.user.is_authenticated:
        if request.method == "POST":
            ident = request.POST.get("username_or_email", "").strip()
            password = request.POST.get("password", "")
            user = authenticate(request, username=ident, password=password)

            if user is not None:
                if not user.is_active:
                    messages.error(request, "This account is inactive. Please contact your administrator.")
                else:
                    is_member = WorkspaceMembership.objects.filter(
                        workspace=workspace,
                        user=user,
                        is_active=True
                    ).exists()
                    is_platform_admin = getattr(user, "is_platform_admin", False)

                    if not is_member and not is_platform_admin:
                        messages.error(request, f"Access Denied: {ident} is not an authorized member of {workspace.name}.")
                    else:
                        login(request, user)
                        messages.success(request, f"Welcome to {workspace.name} support portal, {user.first_name or user.username}!")
                        return redirect("workspace_dashboard", company_slug=workspace.slug)
            else:
                messages.error(request, "Invalid username/email or password.")

        return render(request, "workspace/company_landing.html", {
            "workspace": workspace
        })

    # User is authenticated - check workspace membership
    membership = getattr(request, "membership", None)
    is_platform_admin = getattr(request.user, "is_platform_admin", False)
    if not membership and not is_platform_admin:
        return HttpResponseForbidden(f"Access Denied: You are not an active member of {workspace.name}.")

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
        "active_nav": "settings"
    })
