import logging
from django.utils import timezone
from apps.knowledge_base.models import KnowledgeDocument
from apps.tickets.models import Ticket, TicketAssignment, TicketEvent
from apps.teams.models import Team
from apps.customers.models import Customer
from apps.conversations.models import Conversation
from apps.ai_engine.models import ToolExecution
from services.ai.rag_service import rag_service

logger = logging.getLogger(__name__)

class ToolRegistry:
    """
    Registry of controlled AI tools. Every tool is strictly workspace-scoped
    and audited. Never exposes raw SQL or unrestricted file system access.
    """

    @staticmethod
    def search_knowledge_base(workspace_id: int, query: str) -> dict:
        results = rag_service.retrieve_context(workspace_id=workspace_id, query=query, top_k=3)
        return {
            "success": True,
            "count": len(results),
            "results": results
        }

    @staticmethod
    def create_ticket(workspace_id: int, customer_id: int, subject: str, description: str, priority: str = "MEDIUM", category: str = "General Support") -> dict:
        try:
            customer = Customer.objects.get(id=customer_id, workspace_id=workspace_id)
            valid_priority = priority if priority in Ticket.Priority.values else Ticket.Priority.MEDIUM

            ticket = Ticket.objects.create(
                workspace_id=workspace_id,
                customer=customer,
                subject=subject[:255],
                description=description,
                priority=valid_priority,
                category=category[:100],
                status=Ticket.Status.OPEN
            )
            TicketEvent.objects.create(
                ticket=ticket,
                event_type="AI_CREATED",
                description=f"Ticket created automatically by AI Agent. Priority: {ticket.priority}"
            )
            return {
                "success": True,
                "ticket_id": ticket.id,
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "priority": ticket.priority
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def get_ticket_status(workspace_id: int, ticket_number: str) -> dict:
        try:
            ticket = Ticket.objects.get(workspace_id=workspace_id, ticket_number=ticket_number.strip().upper())
            return {
                "success": True,
                "ticket_number": ticket.ticket_number,
                "subject": ticket.subject,
                "status": ticket.status,
                "priority": ticket.priority,
                "assigned_team": ticket.assigned_team.name if ticket.assigned_team else "Unassigned",
                "created_at": ticket.created_at.strftime("%Y-%m-%d %H:%M")
            }
        except Ticket.DoesNotExist:
            return {"success": False, "error": f"Ticket '{ticket_number}' not found."}

    @staticmethod
    def assign_ticket(workspace_id: int, ticket_id: int, team_id: int) -> dict:
        try:
            ticket = Ticket.objects.get(id=ticket_id, workspace_id=workspace_id)
            team = Team.objects.get(id=team_id, workspace_id=workspace_id, is_active=True)

            prev_team = ticket.assigned_team
            ticket.assigned_team = team
            ticket.save(update_fields=["assigned_team", "updated_at"])

            TicketAssignment.objects.create(
                ticket=ticket,
                previous_team=prev_team,
                new_team=team,
                reason="Assigned by AI Agent"
            )
            TicketEvent.objects.create(
                ticket=ticket,
                event_type="TEAM_ASSIGNED",
                description=f"Assigned to team '{team.name}' by AI Agent."
            )
            return {"success": True, "ticket_number": ticket.ticket_number, "assigned_team": team.name}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def escalate_to_human(workspace_id: int, conversation_id: int, reason: str) -> dict:
        try:
            conv = Conversation.objects.get(id=conversation_id, workspace_id=workspace_id)
            conv.is_escalated = True
            conv.urgency = Conversation.Urgency.CRITICAL
            conv.save(update_fields=["is_escalated", "urgency", "updated_at"])

            # Create or update ticket immediately for urgent escalation
            ticket = getattr(conv, "ticket", None)
            if not ticket:
                # Find appropriate team (e.g. Billing or first available team)
                team = Team.objects.filter(workspace_id=workspace_id, is_active=True).first()
                ticket = Ticket.objects.create(
                    workspace_id=workspace_id,
                    customer=conv.customer,
                    conversation=conv,
                    subject=f"Urgent Escalation: {reason[:100]}",
                    description=f"Immediate AI Escalation.\nReason: {reason}\nConversation #{conv.id}",
                    priority=Ticket.Priority.CRITICAL,
                    category="Urgent Escalation",
                    assigned_team=team,
                    status=Ticket.Status.OPEN
                )
            else:
                ticket.priority = Ticket.Priority.CRITICAL
                ticket.escalation_reason = reason
                ticket.save(update_fields=["priority", "escalation_reason", "updated_at"])

            return {
                "success": True,
                "escalated": True,
                "ticket_id": ticket.id,
                "ticket_number": ticket.ticket_number,
                "priority": ticket.priority
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

tool_registry = ToolRegistry()

