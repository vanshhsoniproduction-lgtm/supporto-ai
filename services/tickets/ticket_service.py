import logging
from django.utils import timezone
from apps.tickets.models import Ticket, TicketAssignment, TicketComment, TicketEvent
from apps.teams.models import Team
from services.ai.llm_service import llm_service

logger = logging.getLogger(__name__)

class TicketService:
    """Manages ticket lifecycle, transitions, assignments, and events."""

    @classmethod
    def create_or_update_from_conversation(cls, conversation) -> Ticket:
        """
        Creates or updates a ticket from a conversation.
        Guarantees idempotency (prevents duplicate tickets on repeated completion requests).
        """
        # If ticket already exists for this conversation, return it
        if hasattr(conversation, "ticket") and conversation.ticket:
            return conversation.ticket

        existing = Ticket.objects.filter(conversation=conversation).first()
        if existing:
            return existing

        workspace = conversation.workspace
        customer = conversation.customer

        messages = list(conversation.messages.values("sender_type", "content"))
        summary = llm_service.summarize_conversation(messages)
        conversation.summary = summary
        conversation.save(update_fields=["summary", "updated_at"])

        # Determine priority based on conversation urgency
        urgency_map = {
            "CRITICAL": Ticket.Priority.CRITICAL,
            "HIGH": Ticket.Priority.HIGH,
            "MEDIUM": Ticket.Priority.MEDIUM,
            "LOW": Ticket.Priority.LOW,
        }
        priority = urgency_map.get(conversation.urgency, Ticket.Priority.MEDIUM)

        # Route team
        assigned_team = llm_service.recommend_team_routing(workspace, conversation.intent or summary)

        subject = f"{conversation.intent or 'Support Request'} - {customer.name}"
        ticket = Ticket.objects.create(
            workspace=workspace,
            customer=customer,
            conversation=conversation,
            subject=subject[:255],
            description=summary,
            category=conversation.intent or "General Support",
            priority=priority,
            status=Ticket.Status.OPEN,
            assigned_team=assigned_team,
        )

        TicketEvent.objects.create(
            ticket=ticket,
            event_type="CREATED_FROM_CONVERSATION",
            description=f"Ticket generated upon conversation completion. Assigned to team '{assigned_team.name if assigned_team else 'Unassigned'}'."
        )

        return ticket

    @classmethod
    def assign_ticket(cls, ticket: Ticket, new_team=None, new_agent=None, assigned_by=None, reason="") -> Ticket:
        """Assigns ticket to team and/or agent with audit logging."""
        prev_team = ticket.assigned_team
        prev_agent = ticket.assigned_agent

        ticket.assigned_team = new_team if new_team is not None else ticket.assigned_team
        ticket.assigned_agent = new_agent
        ticket.save(update_fields=["assigned_team", "assigned_agent", "updated_at"])

        TicketAssignment.objects.create(
            ticket=ticket,
            assigned_by=assigned_by,
            previous_team=prev_team,
            new_team=ticket.assigned_team,
            previous_agent=prev_agent,
            new_agent=ticket.assigned_agent,
            reason=reason
        )

        desc = f"Assignment changed: Team: {ticket.assigned_team.name if ticket.assigned_team else 'None'}, Agent: {ticket.assigned_agent.full_name if ticket.assigned_agent else 'None'}."
        TicketEvent.objects.create(
            ticket=ticket,
            actor=assigned_by,
            event_type="REASSIGNED",
            description=desc
        )
        return ticket

    @classmethod
    def update_status(cls, ticket: Ticket, new_status: str, actor=None, comment: str = "") -> Ticket:
        """Updates ticket status with validation and optional comment."""
        if new_status not in Ticket.Status.values:
            raise ValueError(f"Invalid ticket status: {new_status}")

        old_status = ticket.status
        ticket.status = new_status
        if new_status in (Ticket.Status.RESOLVED, Ticket.Status.CLOSED) and not ticket.resolved_at:
            ticket.resolved_at = timezone.now()
        ticket.save(update_fields=["status", "resolved_at", "updated_at"])

        TicketEvent.objects.create(
            ticket=ticket,
            actor=actor,
            event_type="STATUS_CHANGED",
            description=f"Status changed from {old_status} to {new_status}."
        )

        if comment:
            TicketComment.objects.create(
                ticket=ticket,
                author=actor,
                is_internal=True,
                content=comment
            )

        return ticket

ticket_service = TicketService()

