from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator
from apps.customers.models import Customer
from apps.tickets.models import Ticket
from apps.conversations.models import Conversation
from apps.emails.models import InboundEmail
from services.workspaces.access_control import require_workspace_roles

@require_workspace_roles("OWNER", "ADMIN", "MANAGER", "AGENT")
def customer_list_view(request, company_slug):
    """Lists customers strictly scoped to the active workspace with search and company filters."""
    workspace = request.workspace
    query = request.GET.get("q", "").strip()
    source_filter = request.GET.get("source", "").strip().upper()
    company_filter = request.GET.get("company", "").strip()

    customers_qs = Customer.objects.filter(workspace=workspace)

    if query:
        customers_qs = customers_qs.filter(
            name__icontains=query
        ) | customers_qs.filter(
            email__icontains=query
        ) | customers_qs.filter(
            phone__icontains=query
        ) | customers_qs.filter(
            company__icontains=query
        )

    if source_filter and source_filter in Customer.Source.values:
        customers_qs = customers_qs.filter(source=source_filter)

    if company_filter:
        customers_qs = customers_qs.filter(company__icontains=company_filter)

    customers_qs = customers_qs.order_by("-last_seen")
    paginator = Paginator(customers_qs, 20)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    return render(request, "customers/customer_list.html", {
        "workspace": workspace,
        "customers": page_obj,
        "query": query,
        "source_filter": source_filter,
        "company_filter": company_filter,
        "active_nav": "customers"
    })


@require_workspace_roles("OWNER", "ADMIN", "MANAGER", "AGENT")
def customer_detail_view(request, company_slug, customer_id):
    """
    Detailed Customer 360 profile:
    - Customer details & metadata
    - Email history
    - Chat & voice conversations
    - Open and resolved tickets
    - Sentiment history
    - Internal staff notes
    """
    workspace = request.workspace
    customer = get_object_or_404(Customer, id=customer_id, workspace=workspace)

    if request.method == "POST":
        customer.name = request.POST.get("name", customer.name).strip() or customer.name
        customer.phone = request.POST.get("phone", customer.phone).strip()
        customer.company = request.POST.get("company", customer.company).strip()
        customer.status = request.POST.get("status", customer.status).strip()
        customer.internal_notes = request.POST.get("internal_notes", customer.internal_notes).strip()
        customer.save()
        messages.success(request, f"Customer profile for {customer.display_name} updated successfully.")
        return redirect("customer_detail", company_slug=workspace.slug, customer_id=customer.id)

    # Scoped related data
    tickets = Ticket.objects.filter(workspace=workspace, customer=customer).select_related(
        "assigned_team", "assigned_agent"
    ).order_by("-created_at")

    open_tickets = [t for t in tickets if t.status not in (Ticket.Status.RESOLVED, Ticket.Status.CLOSED)]
    resolved_tickets = [t for t in tickets if t.status in (Ticket.Status.RESOLVED, Ticket.Status.CLOSED)]

    conversations = Conversation.objects.filter(workspace=workspace, customer=customer).order_by("-created_at")

    emails = InboundEmail.objects.filter(workspace=workspace, linked_customer=customer).order_by("-received_at")

    # Sentiment distribution
    sentiment_history = [
        {"timestamp": c.created_at, "sentiment": c.sentiment, "channel": c.channel, "summary": c.summary}
        for c in conversations
    ]

    return render(request, "customers/customer_detail.html", {
        "workspace": workspace,
        "customer": customer,
        "tickets": tickets,
        "open_tickets": open_tickets,
        "resolved_tickets": resolved_tickets,
        "conversations": conversations,
        "emails": emails,
        "sentiment_history": sentiment_history,
        "active_nav": "customers"
    })
