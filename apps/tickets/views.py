from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.views.decorators.http import require_POST
from apps.tickets.models import Ticket, TicketComment
from apps.teams.models import Team, TeamMembership
from apps.customers.models import Customer
from services.tickets.ticket_service import ticket_service

def ticket_list_view(request, company_slug):
    workspace = request.workspace
    tickets = Ticket.objects.filter(workspace=workspace).select_related(
        "customer", "assigned_team", "assigned_agent"
    )

    # Search query
    q = request.GET.get("q", "").strip()
    if q:
        tickets = tickets.filter(
            Q(ticket_number__icontains=q) |
            Q(subject__icontains=q) |
            Q(description__icontains=q) |
            Q(customer__name__icontains=q) |
            Q(customer__email__icontains=q)
        )

    # Status filter
    status = request.GET.get("status", "")
    if status and status in Ticket.Status.values:
        tickets = tickets.filter(status=status)

    # Priority filter
    priority = request.GET.get("priority", "")
    if priority and priority in Ticket.Priority.values:
        tickets = tickets.filter(priority=priority)

    # Team filter
    team_id = request.GET.get("team", "")
    if team_id:
        tickets = tickets.filter(assigned_team_id=team_id)

    paginator = Paginator(tickets, 15)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    teams = Team.objects.filter(workspace=workspace, is_active=True)

    return render(request, "tickets/ticket_list.html", {
        "workspace": workspace,
        "page_obj": page_obj,
        "teams": teams,
        "filter_status": status,
        "filter_priority": priority,
        "filter_team": team_id,
        "query": q,
        "view_type": "all",
        "active_nav": "tickets"
    })


def my_tickets_view(request, company_slug):
    workspace = request.workspace
    tickets = Ticket.objects.filter(
        workspace=workspace,
        assigned_agent=request.user
    ).select_related("customer", "assigned_team")

    paginator = Paginator(tickets, 15)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    return render(request, "tickets/ticket_list.html", {
        "workspace": workspace,
        "page_obj": page_obj,
        "view_type": "my",
        "active_nav": "my_tickets"
    })


def team_queue_view(request, company_slug):
    workspace = request.workspace
    user_team_ids = TeamMembership.objects.filter(
        team__workspace=workspace,
        user=request.user
    ).values_list("team_id", flat=True)

    tickets = Ticket.objects.filter(
        workspace=workspace,
        assigned_team_id__in=user_team_ids
    ).select_related("customer", "assigned_team", "assigned_agent")

    paginator = Paginator(tickets, 15)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    return render(request, "tickets/ticket_list.html", {
        "workspace": workspace,
        "page_obj": page_obj,
        "view_type": "queue",
        "active_nav": "team_queue"
    })


def ticket_detail_view(request, company_slug, ticket_number):
    workspace = request.workspace
    ticket = get_object_or_404(
        Ticket.objects.select_related("customer", "assigned_team", "assigned_agent", "conversation"),
        workspace=workspace,
        ticket_number=ticket_number
    )

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add_comment":
            content = request.POST.get("content", "").strip()
            is_internal = request.POST.get("is_internal") == "true"
            if content:
                TicketComment.objects.create(
                    ticket=ticket,
                    author=request.user,
                    is_internal=is_internal,
                    content=content
                )
                messages.success(request, "Note added to ticket." if is_internal else "Customer reply recorded.")
                return redirect("ticket_detail", company_slug=workspace.slug, ticket_number=ticket.ticket_number)

        elif action == "update_status":
            new_status = request.POST.get("status")
            if new_status in Ticket.Status.values:
                ticket_service.update_status(ticket, new_status, actor=request.user)
                messages.success(request, f"Status updated to {new_status}.")
                return redirect("ticket_detail", company_slug=workspace.slug, ticket_number=ticket.ticket_number)

        elif action == "update_assignment":
            team_id = request.POST.get("team_id")
            agent_id = request.POST.get("agent_id")
            team = Team.objects.filter(id=team_id, workspace=workspace).first() if team_id else None
            agent = workspace.memberships.filter(user_id=agent_id).first().user if agent_id else None
            ticket_service.assign_ticket(ticket, new_team=team, new_agent=agent, assigned_by=request.user, reason="Manual reassignment")
            messages.success(request, "Ticket assignment updated.")
            return redirect("ticket_detail", company_slug=workspace.slug, ticket_number=ticket.ticket_number)

    comments = ticket.comments.select_related("author").order_by("created_at")
    events = ticket.events.select_related("actor").order_by("-created_at")[:20]
    conversation_messages = ticket.conversation.messages.order_by("created_at") if ticket.conversation else []
    inbound_emails = ticket.inbound_emails.all().order_by("-received_at")

    teams = Team.objects.filter(workspace=workspace, is_active=True)
    staff_members = workspace.memberships.filter(is_active=True).select_related("user")

    return render(request, "tickets/ticket_detail.html", {
        "workspace": workspace,
        "ticket": ticket,
        "comments": comments,
        "events": events,
        "conversation_messages": conversation_messages,
        "inbound_emails": inbound_emails,
        "teams": teams,
        "staff_members": staff_members,
        "active_nav": "tickets"
    })
