from django.utils import timezone
from apps.conversations.models import Conversation
from apps.customers.models import Customer
from apps.workspaces.models import Workspace
from services.tickets.ticket_service import ticket_service

class ConversationService:
    """Manages conversations, customers, and finalization."""

    @staticmethod
    def get_or_create_customer(workspace: Workspace, session_token: str, name: str = "", email: str = "") -> Customer:
        if session_token:
            customer = Customer.objects.filter(workspace=workspace, session_token=session_token).first()
            if customer:
                if name and customer.name == "Visitor":
                    customer.name = name
                if email and not customer.email:
                    customer.email = email
                    customer.is_anonymous = False
                customer.save()
                return customer

        customer = Customer.objects.create(
            workspace=workspace,
            name=name if name else "Visitor",
            email=email,
            session_token=session_token,
            is_anonymous=not bool(email)
        )
        return customer

    @staticmethod
    def start_conversation(workspace: Workspace, customer: Customer, channel: str = Conversation.Channel.WEB_CHAT) -> Conversation:
        # Check if there is an active conversation for this customer
        active_conv = Conversation.objects.filter(
            workspace=workspace,
            customer=customer,
            status=Conversation.Status.ACTIVE
        ).first()

        if active_conv:
            return active_conv

        conv = Conversation.objects.create(
            workspace=workspace,
            customer=customer,
            channel=channel,
            status=Conversation.Status.ACTIVE
        )
        return conv

    @staticmethod
    def finalize_conversation(conversation: Conversation) -> dict:
        """Finalizes conversation, updates metrics, and ensures ticket generation."""
        if conversation.status == Conversation.Status.COMPLETED:
            ticket = getattr(conversation, "ticket", None)
            return {
                "conversation_id": conversation.id,
                "status": "COMPLETED",
                "ticket_number": ticket.ticket_number if ticket else None
            }

        conversation.status = Conversation.Status.COMPLETED
        conversation.save(update_fields=["status", "updated_at"])

        ticket = ticket_service.create_or_update_from_conversation(conversation)

        return {
            "conversation_id": conversation.id,
            "status": "COMPLETED",
            "ticket_id": ticket.id,
            "ticket_number": ticket.ticket_number,
            "assigned_team": ticket.assigned_team.name if ticket.assigned_team else "None"
        }

conversation_service = ConversationService()

