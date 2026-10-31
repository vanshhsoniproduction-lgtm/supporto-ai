from django.utils import timezone
from apps.conversations.models import Conversation
from apps.customers.models import Customer
from apps.workspaces.models import Workspace
from apps.orders.utils import normalize_phone
from services.tickets.ticket_service import ticket_service

class ConversationService:
    """Manages conversations, customers, and finalization."""

    @staticmethod
    def get_or_create_customer(workspace: Workspace, session_token: str, name: str = "", email: str = "", phone: str = "") -> Customer:
        norm_phone = normalize_phone(phone) if phone else ""

        # 1. Match by normalized_phone within the workspace if provided
        if norm_phone:
            customer = Customer.objects.filter(workspace=workspace, normalized_phone=norm_phone).first()
            if customer:
                changed = False
                if name and customer.name in ("Visitor", ""):
                    customer.name = name
                    changed = True
                if email and not customer.email:
                    customer.email = email
                    customer.is_anonymous = False
                    changed = True
                if session_token and customer.session_token != session_token:
                    customer.session_token = session_token
                    changed = True
                if changed:
                    customer.save()
                return customer

        # 2. Match by session_token within the workspace
        if session_token:
            customer = Customer.objects.filter(workspace=workspace, session_token=session_token).first()
            if customer:
                changed = False
                if name and customer.name in ("Visitor", ""):
                    customer.name = name
                    changed = True
                if email and not customer.email:
                    customer.email = email
                    customer.is_anonymous = False
                    changed = True
                if norm_phone and not customer.normalized_phone:
                    customer.phone = phone
                    customer.normalized_phone = norm_phone
                    customer.is_anonymous = False
                    changed = True
                if changed:
                    customer.save()
                return customer

        # 3. Create new customer
        customer = Customer.objects.create(
            workspace=workspace,
            name=name if name else "Visitor",
            email=email,
            phone=phone,
            normalized_phone=norm_phone,
            session_token=session_token,
            is_anonymous=not bool(email or norm_phone)
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
