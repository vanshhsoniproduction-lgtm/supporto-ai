import logging
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from apps.emails.models import MailboxConnection, InboundEmail, TicketProposal
from apps.emails.services.gmail_service import gmail_service
from apps.teams.models import Team, TeamMembership
from apps.tickets.models import Ticket, TicketAssignment, TicketEvent
from apps.analytics.models import AuditLog
from services.workspaces.access_control import require_workspace_roles

logger = logging.getLogger(__name__)
User = get_user_model()

@require_workspace_roles("OWNER", "ADMIN", "MANAGER", "AGENT")
def email_inbox_view(request, company_slug):
    """
    Centralized 3-panel Email Inbox:
    - Left: Folders / filters
    - Center: Filterable, searchable email list
    - Right: Selected email inspection, AI triage analysis, and action controls
    """
    workspace = request.workspace
    filter_status = request.GET.get("filter", "all").strip().lower()
    search_query = request.GET.get("q", "").strip()
    selected_id = request.GET.get("selected")

    emails_qs = InboundEmail.objects.filter(workspace=workspace).select_related(
        "linked_customer", "linked_ticket", "proposal", "mailbox_connection"
    )

    # Apply filters
    if filter_status == "new":
        emails_qs = emails_qs.filter(processing_status=InboundEmail.ProcessingStatus.NEW)
    elif filter_status == "analyzed":
        emails_qs = emails_qs.filter(processing_status=InboundEmail.ProcessingStatus.ANALYZED)
    elif filter_status == "pending_review":
        emails_qs = emails_qs.filter(processing_status=InboundEmail.ProcessingStatus.TICKET_PROPOSED)
    elif filter_status == "ticket_approved":
        emails_qs = emails_qs.filter(processing_status=InboundEmail.ProcessingStatus.TICKET_APPROVED)
    elif filter_status == "no_ticket":
        emails_qs = emails_qs.filter(processing_status=InboundEmail.ProcessingStatus.NO_TICKET)
    elif filter_status == "rejected":
        emails_qs = emails_qs.filter(processing_status=InboundEmail.ProcessingStatus.REJECTED)
    elif filter_status == "failed":
        emails_qs = emails_qs.filter(processing_status=InboundEmail.ProcessingStatus.FAILED)

    # Apply search
    if search_query:
        emails_qs = emails_qs.filter(
            subject__icontains=search_query
        ) | emails_qs.filter(
            sender_email__icontains=search_query
        ) | emails_qs.filter(
            sender_name__icontains=search_query
        ) | emails_qs.filter(
            normalized_text_body__icontains=search_query
        )

    emails_qs = emails_qs.order_by("-received_at")
    paginator = Paginator(emails_qs, 20)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    # Selected email
    selected_email = None
    if selected_id:
        selected_email = InboundEmail.objects.filter(workspace=workspace, id=selected_id).select_related(
            "linked_customer", "linked_ticket", "proposal", "mailbox_connection"
        ).first()
    if not selected_email and page_obj.object_list:
        selected_email = page_obj.object_list[0]

    # Metrics counts for filter badges
    base_qs = InboundEmail.objects.filter(workspace=workspace)
    counts = {
        "all": base_qs.count(),
        "pending_review": base_qs.filter(processing_status=InboundEmail.ProcessingStatus.TICKET_PROPOSED).count(),
        "ticket_approved": base_qs.filter(processing_status=InboundEmail.ProcessingStatus.TICKET_APPROVED).count(),
        "no_ticket": base_qs.filter(processing_status=InboundEmail.ProcessingStatus.NO_TICKET).count(),
        "rejected": base_qs.filter(processing_status=InboundEmail.ProcessingStatus.REJECTED).count(),
    }

    # Available teams for inline approval
    teams = Team.objects.filter(workspace=workspace, is_active=True).prefetch_related("memberships__user")

    # Connected mailboxes info
    connections = MailboxConnection.objects.filter(workspace=workspace)

    return render(request, "emails/inbox.html", {
        "workspace": workspace,
        "emails": page_obj,
        "selected_email": selected_email,
        "filter_status": filter_status,
        "search_query": search_query,
        "counts": counts,
        "teams": teams,
        "connections": connections,
        "active_nav": "emails"
    })


@require_workspace_roles("OWNER", "ADMIN", "MANAGER", "AGENT")
def email_review_queue_view(request, company_slug):
    """
    Dedicated Human Review Queue for AI Ticket Proposals.
    Orders Critical items first. Human review and team selection are mandatory.
    """
    workspace = request.workspace
    proposals = TicketProposal.objects.filter(
        workspace=workspace,
        approval_status=TicketProposal.ApprovalStatus.PENDING_REVIEW
    ).select_related(
        "inbound_email", "customer", "ai_recommended_team"
    ).order_by("-ai_urgency", "-created_at")

    # Sort so CRITICAL appears at the absolute top
    priority_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    proposals_list = sorted(list(proposals), key=lambda p: priority_order.get(p.ai_urgency, 4))

    teams = Team.objects.filter(workspace=workspace, is_active=True).prefetch_related("memberships__user")

    return render(request, "emails/review_queue.html", {
        "workspace": workspace,
        "proposals": proposals_list,
        "teams": teams,
        "active_nav": "pending_reviews"
    })


@require_workspace_roles("OWNER", "ADMIN", "MANAGER", "AGENT")
@require_POST
def proposal_action_view(request, company_slug, proposal_id):
    """
    Handles human review actions:
    1. Approve Ticket (requires valid workspace team assignment)
    2. Reject Proposal (stores rejection reason)
    3. Edit Proposal
    4. Mark No Ticket Required
    """
    workspace = request.workspace
    proposal = get_object_or_404(TicketProposal, id=proposal_id, workspace=workspace)
    action = request.POST.get("action", "").strip().lower()

    if action == "approve":
        # Validate that proposal is not already approved
        if proposal.approval_status == TicketProposal.ApprovalStatus.APPROVED and proposal.created_ticket:
            messages.warning(request, f"This proposal has already been approved as Ticket #{proposal.created_ticket.ticket_number}.")
            return redirect("email_review_queue", company_slug=workspace.slug)

        # Team selection is strictly mandatory
        team_id = request.POST.get("assigned_team_id")
        if not team_id:
            messages.error(request, "Team selection is mandatory to approve a ticket.")
            return redirect("email_review_queue", company_slug=workspace.slug)

        team = get_object_or_404(Team, id=team_id, workspace=workspace)

        # Optional Agent selection (must belong to selected team)
        agent = None
        agent_id = request.POST.get("assigned_agent_id")
        if agent_id:
            agent = User.objects.filter(id=agent_id).first()
            if agent:
                is_member = TeamMembership.objects.filter(team=team, user=agent).exists()
                if not is_member:
                    messages.error(request, f"Selected agent {agent.email} is not a member of {team.name}.")
                    return redirect("email_review_queue", company_slug=workspace.slug)

        # Editable fields
        subject = request.POST.get("proposed_subject", proposal.proposed_subject).strip() or proposal.proposed_subject
        description = request.POST.get("proposed_description", proposal.proposed_description).strip() or proposal.proposed_description
        category = request.POST.get("proposed_category", proposal.proposed_category).strip() or proposal.proposed_category
        priority = request.POST.get("proposed_priority", proposal.proposed_priority).strip() or proposal.proposed_priority
        edited_reply = request.POST.get("edited_suggested_reply", proposal.edited_suggested_reply).strip()
        review_notes = request.POST.get("review_notes", "").strip()

        with transaction.atomic():
            # Create the actual Ticket
            ticket = Ticket.objects.create(
                workspace=workspace,
                customer=proposal.customer,
                conversation=proposal.conversation,
                subject=subject,
                description=description,
                category=category,
                priority=priority,
                status=Ticket.Status.OPEN,
                assigned_team=team,
                assigned_agent=agent,
                escalation_reason=f"Approved from AI Email Triage (Intent: {proposal.ai_intent})"
            )

            # Create TicketAssignment record
            TicketAssignment.objects.create(
                ticket=ticket,
                assigned_by=request.user,
                new_team=team,
                new_agent=agent,
                reason="Initial assignment upon email proposal approval"
            )

            # Record TicketEvent
            TicketEvent.objects.create(
                ticket=ticket,
                actor=request.user,
                event_type="EMAIL_TICKET_APPROVED",
                description=f"Ticket #{ticket.ticket_number} approved from email proposal by {request.user.email} and assigned to {team.name}."
            )

            # Update proposal
            proposal.created_ticket = ticket
            proposal.approval_status = TicketProposal.ApprovalStatus.APPROVED
            proposal.reviewed_by = request.user
            proposal.reviewed_at = timezone.now()
            proposal.proposed_subject = subject
            proposal.proposed_description = description
            proposal.proposed_category = category
            proposal.proposed_priority = priority
            proposal.edited_suggested_reply = edited_reply
            proposal.review_notes = review_notes
            proposal.save()

            # Update InboundEmail
            inbound_email = proposal.inbound_email
            inbound_email.linked_ticket = ticket
            inbound_email.processing_status = InboundEmail.ProcessingStatus.TICKET_APPROVED
            inbound_email.save(update_fields=["linked_ticket", "processing_status"])

            # AuditLog
            AuditLog.objects.create(
                workspace=workspace,
                actor=request.user,
                action="TICKET_PROPOSAL_APPROVED",
                resource_type="TicketProposal",
                resource_id=str(proposal.id),
                details={"ticket_number": ticket.ticket_number, "team": team.name, "agent": agent.email if agent else None}
            )

        messages.success(request, f"Ticket #{ticket.ticket_number} successfully created and assigned to {team.name}!")
        return redirect("ticket_detail", company_slug=workspace.slug, ticket_number=ticket.ticket_number)

    elif action == "reject":
        review_notes = request.POST.get("review_notes", "Rejected by support staff.").strip()
        proposal.approval_status = TicketProposal.ApprovalStatus.REJECTED
        proposal.reviewed_by = request.user
        proposal.reviewed_at = timezone.now()
        proposal.review_notes = review_notes
        proposal.save()

        inbound_email = proposal.inbound_email
        inbound_email.processing_status = InboundEmail.ProcessingStatus.REJECTED
        inbound_email.save(update_fields=["processing_status"])

        AuditLog.objects.create(
            workspace=workspace,
            actor=request.user,
            action="TICKET_PROPOSAL_REJECTED",
            resource_type="TicketProposal",
            resource_id=str(proposal.id),
            details={"reason": review_notes}
        )
        messages.info(request, f"Proposal #{proposal.id} rejected. Original email remains safely preserved.")
        return redirect("email_review_queue", company_slug=workspace.slug)

    elif action == "no_ticket":
        proposal.approval_status = TicketProposal.ApprovalStatus.NO_TICKET_REQUIRED
        proposal.reviewed_by = request.user
        proposal.reviewed_at = timezone.now()
        proposal.save()

        inbound_email = proposal.inbound_email
        inbound_email.processing_status = InboundEmail.ProcessingStatus.NO_TICKET
        inbound_email.save(update_fields=["processing_status"])

        messages.info(request, f"Proposal marked as 'No Ticket Required'.")
        return redirect("email_review_queue", company_slug=workspace.slug)

    elif action == "edit":
        proposal.proposed_subject = request.POST.get("proposed_subject", proposal.proposed_subject).strip()
        proposal.proposed_description = request.POST.get("proposed_description", proposal.proposed_description).strip()
        proposal.proposed_category = request.POST.get("proposed_category", proposal.proposed_category).strip()
        proposal.proposed_priority = request.POST.get("proposed_priority", proposal.proposed_priority).strip()
        proposal.edited_suggested_reply = request.POST.get("edited_suggested_reply", proposal.edited_suggested_reply).strip()
        proposal.save()
        messages.success(request, "Proposal details updated successfully.")
        return redirect("email_review_queue", company_slug=workspace.slug)

    return redirect("email_review_queue", company_slug=workspace.slug)


@require_workspace_roles("OWNER", "ADMIN", "MANAGER", "AGENT")
@require_POST
def sync_now_view(request, company_slug):
    """Triggers an immediate synchronization for all active mailboxes in this workspace."""
    workspace = request.workspace
    connections = MailboxConnection.objects.filter(workspace=workspace, status=MailboxConnection.Status.ACTIVE)

    if not connections.exists():
        messages.warning(request, "No active mailbox connection found. Please connect your Gmail mailbox in Email Integration Settings.")
        return redirect("email_inbox", company_slug=workspace.slug)

    total_synced = 0
    errors = []
    for conn in connections:
        try:
            count = gmail_service.sync_mailbox(conn)
            total_synced += count
        except Exception as e:
            errors.append(f"{conn.email_address}: {str(e)[:150]}")

    if errors:
        messages.error(request, f"Sync completed with errors: {'; '.join(errors)}")
    else:
        messages.success(request, f"Mailbox sync completed! {total_synced} new email(s) retrieved and processed.")

    return redirect("email_inbox", company_slug=workspace.slug)


@require_workspace_roles("OWNER", "ADMIN")
def gmail_connect_view(request, company_slug):
    """
    Dedicated Mailbox Connection settings:
    Allows authorized workspace admin to connect their support mailbox via Gmail OAuth.
    """
    workspace = request.workspace
    connections = MailboxConnection.objects.filter(workspace=workspace)
    client_id = getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "")
    oauth_url = gmail_service.get_oauth_authorization_url(workspace.slug) if client_id else ""

    return render(request, "emails/gmail_settings.html", {
        "workspace": workspace,
        "connections": connections,
        "client_id_configured": bool(client_id),
        "oauth_url": oauth_url,
        "active_nav": "email_integration"
    })


def global_gmail_callback_view(request):
    """
    Global OAuth Callback for Gmail Mailbox Authorization:
    Exchanges code for tokens, encrypts tokens, and stores MailboxConnection.
    """
    error = request.GET.get("error")
    if error:
        messages.error(request, f"Gmail integration authorization failed: {error}")
        return redirect("landing")

    code = request.GET.get("code")
    state = request.GET.get("state", "")

    workspace_slug = ""
    if state and state.startswith("gmail_sync:"):
        workspace_slug = state.split(":", 1)[1]

    if not workspace_slug:
        messages.error(request, "Invalid OAuth state for Gmail integration.")
        return redirect("landing")

    from apps.workspaces.models import Workspace
    workspace = get_object_or_404(Workspace, slug=workspace_slug)

    if not code:
        messages.error(request, "No authorization code received from Google.")
        return redirect("gmail_connect", company_slug=workspace.slug)

    try:
        connection = gmail_service.handle_oauth_callback(code, workspace)
        messages.success(request, f"Gmail mailbox '{connection.email_address}' successfully connected to {workspace.name}!")
    except Exception as e:
        messages.error(request, f"Failed to complete Gmail mailbox connection: {e}")

    return redirect("gmail_connect", company_slug=workspace.slug)


@require_workspace_roles("OWNER", "ADMIN")
@require_POST
def disconnect_mailbox_view(request, company_slug, connection_id):
    """Disconnects and revokes a mailbox connection."""
    workspace = request.workspace
    conn = get_object_or_404(MailboxConnection, id=connection_id, workspace=workspace)
    conn.status = MailboxConnection.Status.DISCONNECTED
    conn.encrypted_access_token = ""
    conn.encrypted_refresh_token = ""
    conn.save(update_fields=["status", "encrypted_access_token", "encrypted_refresh_token", "updated_at"])

    messages.info(request, f"Mailbox {conn.email_address} has been disconnected.")
    return redirect("gmail_connect", company_slug=workspace.slug)
