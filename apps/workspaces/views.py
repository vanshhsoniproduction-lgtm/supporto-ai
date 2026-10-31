from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.conf import settings
from django.http import HttpResponseForbidden
from apps.workspaces.models import Workspace, WorkspaceSettings, WorkspaceMembership, WorkspaceAuthorizedEmail, WorkspaceWebhook
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
        action = request.POST.get("action", "save_settings")

        if action == "add_authorized_email":
            email_to_add = request.POST.get("email", "").strip().lower()
            role_to_assign = request.POST.get("assigned_role", WorkspaceMembership.Role.AGENT)
            if email_to_add:
                auth_rec, created = WorkspaceAuthorizedEmail.objects.get_or_create(
                    workspace=workspace,
                    normalized_email=email_to_add,
                    defaults={
                        "email": email_to_add,
                        "assigned_role": role_to_assign,
                        "status": WorkspaceAuthorizedEmail.Status.AUTHORIZED,
                        "invited_by": request.user,
                    }
                )
                if not created:
                    auth_rec.assigned_role = role_to_assign
                    auth_rec.status = WorkspaceAuthorizedEmail.Status.AUTHORIZED
                    auth_rec.save(update_fields=["assigned_role", "status"])
                messages.success(request, f"Google email '{email_to_add}' successfully authorized with role {role_to_assign}!")
            return redirect("workspace_settings", company_slug=workspace.slug)

        elif action == "revoke_authorized_email":
            email_id = request.POST.get("email_id")
            WorkspaceAuthorizedEmail.objects.filter(workspace=workspace, id=email_id).delete()
            messages.info(request, "Authorized email removed.")
            return redirect("workspace_settings", company_slug=workspace.slug)

        elif action == "add_webhook":
            wh_name = request.POST.get("name", "Webhook Endpoint").strip()
            wh_url = request.POST.get("url", "").strip()
            wh_type = request.POST.get("webhook_type", WorkspaceWebhook.WebhookType.ORDERS)
            wh_secret = request.POST.get("secret_key", "").strip()
            if wh_url:
                WorkspaceWebhook.objects.create(
                    workspace=workspace,
                    name=wh_name,
                    webhook_type=wh_type,
                    url=wh_url,
                    secret_key=wh_secret,
                    is_active=True
                )
                messages.success(request, f"Webhook endpoint '{wh_name}' added successfully!")
            return redirect("workspace_settings", company_slug=workspace.slug)

        elif action == "delete_webhook":
            wh_id = request.POST.get("webhook_id")
            WorkspaceWebhook.objects.filter(workspace=workspace, id=wh_id).delete()
            messages.info(request, "Webhook endpoint removed.")
            return redirect("workspace_settings", company_slug=workspace.slug)

        # Default: Save general settings
        workspace.name = request.POST.get("name", workspace.name).strip()
        workspace.description = request.POST.get("description", workspace.description).strip()
        workspace.save(update_fields=["name", "description", "updated_at"])

        support_email = request.POST.get("support_email", "").strip().lower()
        settings_obj.company_website = request.POST.get("company_website", "").strip()
        settings_obj.support_email = support_email
        settings_obj.welcome_message = request.POST.get("welcome_message", settings_obj.welcome_message).strip()
        settings_obj.sla_urgent_minutes = int(request.POST.get("sla_urgent_minutes", 30))
        settings_obj.sla_standard_hours = int(request.POST.get("sla_standard_hours", 24))
        settings_obj.ticket_auto_assignment = bool(request.POST.get("ticket_auto_assignment"))
        settings_obj.orders_api_webhook_url = request.POST.get("orders_api_webhook_url", "").strip()
        settings_obj.orders_api_secret_key = request.POST.get("orders_api_secret_key", "").strip()
        settings_obj.customer_verification_secret = request.POST.get("customer_verification_secret", "").strip()
        settings_obj.save()

        # If support_email is provided, ensure it is automatically authorized as OWNER
        if support_email:
            WorkspaceAuthorizedEmail.objects.get_or_create(
                workspace=workspace,
                normalized_email=support_email,
                defaults={
                    "email": support_email,
                    "assigned_role": WorkspaceMembership.Role.OWNER,
                    "status": WorkspaceAuthorizedEmail.Status.AUTHORIZED,
                    "invited_by": request.user,
                }
            )

        messages.success(request, "Company settings saved successfully.")
        return redirect("workspace_settings", company_slug=workspace.slug)

    authorized_emails = WorkspaceAuthorizedEmail.objects.filter(workspace=workspace).order_by("-created_at")
    webhooks = WorkspaceWebhook.objects.filter(workspace=workspace).order_by("-created_at")

    return render(request, "workspace/settings.html", {
        "workspace": workspace,
        "settings": settings_obj,
        "authorized_emails": authorized_emails,
        "webhooks": webhooks,
        "active_nav": "company_settings"
    })
