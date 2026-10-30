import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.views.decorators.http import require_POST
from django.utils.text import slugify
from django.utils import timezone
from apps.workspaces.models import Workspace, WorkspaceMembership, WorkspaceSettings, WorkspaceAuthorizedEmail
from apps.teams.models import Team, TeamMembership
from apps.knowledge_base.models import KnowledgeDocument, KnowledgeChunk
from apps.knowledge_base.services.document_processor import document_processor
from apps.emails.models import MailboxConnection
from apps.emails.services.gmail_service import gmail_service
from apps.ai_engine.models import AgentConfiguration
from apps.voice_support.models import VoiceConfiguration
from apps.analytics.models import AuditLog
from services.workspaces.access_control import require_platform_admin
from services.analytics.metrics_service import metrics_service
from services.ai.model_manager import model_manager

logger = logging.getLogger(__name__)
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

        # Pre-authorize owner email if specified
        if owner_email:
            WorkspaceAuthorizedEmail.objects.create(
                workspace=workspace,
                email=owner_email,
                normalized_email=owner_email,
                assigned_role=WorkspaceMembership.Role.OWNER,
                status=WorkspaceAuthorizedEmail.Status.AUTHORIZED,
                invited_by=request.user,
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
        return redirect("platform_admin_company_detail", slug=workspace.slug)

    workspaces = Workspace.objects.all().prefetch_related("memberships__user", "authorized_emails")
    return render(request, "platform_admin/companies.html", {
        "workspaces": workspaces,
        "active_tab": "companies"
    })


@require_platform_admin
def platform_admin_company_detail(request, slug):
    """Detailed management view for a specific workspace in platform admin."""
    workspace = get_object_or_404(Workspace, slug=slug)
    authorized_emails = WorkspaceAuthorizedEmail.objects.filter(workspace=workspace).prefetch_related("assigned_teams", "linked_user")
    memberships = WorkspaceMembership.objects.filter(workspace=workspace).select_related("user")
    teams = Team.objects.filter(workspace=workspace)
    mailboxes = MailboxConnection.objects.filter(workspace=workspace)
    docs = KnowledgeDocument.objects.filter(workspace=workspace)

    return render(request, "platform_admin/company_detail.html", {
        "workspace": workspace,
        "authorized_emails": authorized_emails,
        "memberships": memberships,
        "teams": teams,
        "mailboxes": mailboxes,
        "docs": docs,
        "active_tab": "companies"
    })


@require_platform_admin
def platform_admin_authorized_emails(request, slug):
    """
    Platform Administrator interface for explicitly authorizing Google emails:
    1. Select company (resolved by slug)
    2. Enter exact Google email
    3. Choose workspace role (OWNER, ADMIN, MANAGER, AGENT)
    4. Optionally assign existing teams
    5. Authorize, revoke, or re-authorize
    """
    workspace = get_object_or_404(Workspace, slug=slug)

    if request.method == "POST":
        action = request.POST.get("action", "authorize")

        if action == "authorize":
            email = request.POST.get("email", "").strip().lower()
            role = request.POST.get("assigned_role", WorkspaceMembership.Role.AGENT)
            team_ids = request.POST.getlist("teams")

            if not email:
                messages.error(request, "An exact Google email address is required.")
                return redirect("platform_admin_authorized_emails", slug=workspace.slug)

            record, created = WorkspaceAuthorizedEmail.objects.get_or_create(
                workspace=workspace,
                normalized_email=email,
                defaults={
                    "email": email,
                    "assigned_role": role,
                    "status": WorkspaceAuthorizedEmail.Status.AUTHORIZED,
                    "invited_by": request.user,
                }
            )

            if not created:
                record.email = email
                record.assigned_role = role
                record.status = WorkspaceAuthorizedEmail.Status.AUTHORIZED
                record.revoked_at = None
                record.authorized_at = timezone.now()
                record.save()

            if team_ids:
                teams = Team.objects.filter(workspace=workspace, id__in=team_ids)
                record.assigned_teams.set(teams)

            AuditLog.objects.create(
                workspace=workspace,
                actor=request.user,
                action="EMAIL_AUTHORIZED",
                resource_type="WorkspaceAuthorizedEmail",
                resource_id=str(record.id),
                details={"email": email, "role": role, "workspace": workspace.slug}
            )
            messages.success(request, f"Google email '{email}' authorized for {workspace.name} as {role}.")
            return redirect("platform_admin_authorized_emails", slug=workspace.slug)

        elif action == "revoke":
            record_id = request.POST.get("record_id")
            record = get_object_or_404(WorkspaceAuthorizedEmail, id=record_id, workspace=workspace)
            record.revoke()

            # Deactivate active membership if exists
            if record.linked_user:
                WorkspaceMembership.objects.filter(workspace=workspace, user=record.linked_user).update(is_active=False)

            AuditLog.objects.create(
                workspace=workspace,
                actor=request.user,
                action="EMAIL_AUTHORIZATION_REVOKED",
                resource_type="WorkspaceAuthorizedEmail",
                resource_id=str(record.id),
                details={"email": record.normalized_email}
            )
            messages.info(request, f"Authorization for '{record.normalized_email}' has been revoked.")
            return redirect("platform_admin_authorized_emails", slug=workspace.slug)

    records = WorkspaceAuthorizedEmail.objects.filter(workspace=workspace).prefetch_related("assigned_teams", "linked_user")
    teams = Team.objects.filter(workspace=workspace, is_active=True)
    roles = WorkspaceMembership.Role.choices

    return render(request, "platform_admin/authorized_emails.html", {
        "workspace": workspace,
        "records": records,
        "teams": teams,
        "roles": roles,
        "active_tab": "companies"
    })


@require_platform_admin
def platform_admin_company_knowledge(request, slug):
    """
    Manages the SAME underlying KnowledgeDocument records for a workspace from Platform Admin.
    """
    workspace = get_object_or_404(Workspace, slug=slug)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add_faq":
            question = request.POST.get("question", "").strip()
            answer = request.POST.get("answer", "").strip()
            title = request.POST.get("title", question[:60]).strip()

            if question and answer:
                doc = KnowledgeDocument.objects.create(
                    workspace=workspace,
                    title=title,
                    doc_type=KnowledgeDocument.DocType.FAQ,
                    question=question,
                    answer=answer,
                    content=f"Q: {question}\nA: {answer}",
                    is_active=True
                )
                document_processor.chunk_and_index(doc)
                messages.success(request, f"FAQ '{title}' added to {workspace.name} Knowledge Base.")
            return redirect("platform_admin_company_knowledge", slug=workspace.slug)

        elif action == "upload_batch":
            files = request.FILES.getlist("files")
            success_count = 0
            for f in files:
                doc, err = document_processor.process_uploaded_document(workspace, f)
                if doc:
                    success_count += 1
            messages.success(request, f"Uploaded {success_count} document(s) to {workspace.name} Knowledge Base.")
            return redirect("platform_admin_company_knowledge", slug=workspace.slug)

    docs = KnowledgeDocument.objects.filter(workspace=workspace).prefetch_related("chunks").order_by("-updated_at")
    return render(request, "platform_admin/company_knowledge.html", {
        "workspace": workspace,
        "documents": docs,
        "active_tab": "companies"
    })


@require_platform_admin
def platform_admin_company_email_integration(request, slug):
    """Platform Admin view of company mailbox connections."""
    workspace = get_object_or_404(Workspace, slug=slug)
    mailboxes = MailboxConnection.objects.filter(workspace=workspace)

    return render(request, "platform_admin/company_email_integration.html", {
        "workspace": workspace,
        "mailboxes": mailboxes,
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
