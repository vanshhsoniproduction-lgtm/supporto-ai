from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from apps.workspaces.models import Workspace, WorkspaceMembership
from apps.tickets.models import Ticket
from apps.conversations.models import Conversation
from apps.teams.models import Team
from apps.ai_engine.models import AgentRun
from services.ai.model_manager import model_manager

User = get_user_model()

class MetricsService:
    """Calculates live analytics strictly derived from database records."""

    @staticmethod
    def get_platform_metrics() -> dict:
        total_companies = Workspace.objects.count()
        active_companies = Workspace.objects.filter(status=Workspace.Status.ACTIVE).count()
        total_users = User.objects.count()
        total_tickets = Ticket.objects.count()
        open_tickets = Ticket.objects.filter(status__in=[Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS]).count()
        ai_health = model_manager.get_health_status()

        return {
            "total_companies": total_companies,
            "active_companies": active_companies,
            "total_users": total_users,
            "total_tickets": total_tickets,
            "open_tickets": open_tickets,
            "ai_health": ai_health,
        }

    @staticmethod
    def get_workspace_metrics(workspace: Workspace) -> dict:
        tickets = Ticket.objects.filter(workspace=workspace)
        open_count = tickets.filter(status=Ticket.Status.OPEN).count()
        in_progress_count = tickets.filter(status=Ticket.Status.IN_PROGRESS).count()
        critical_count = tickets.filter(priority=Ticket.Priority.CRITICAL, status__in=[Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS]).count()
        pending_count = tickets.filter(status=Ticket.Status.PENDING).count()
        resolved_count = tickets.filter(status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED]).count()
        total_tickets = tickets.count()

        teams = Team.objects.filter(workspace=workspace, is_active=True).annotate(
            ticket_count=Count("assigned_tickets")
        )

        conversations = Conversation.objects.filter(workspace=workspace)
        total_conversations = conversations.count()
        escalated_conversations = conversations.filter(is_escalated=True).count()

        agent_runs = AgentRun.objects.filter(workspace=workspace)
        total_agent_runs = agent_runs.count()
        successful_runs = agent_runs.filter(success=True).count()
        ai_success_rate = round((successful_runs / total_agent_runs * 100), 1) if total_agent_runs > 0 else 100.0

        return {
            "total_tickets": total_tickets,
            "open_tickets": open_count,
            "in_progress_tickets": in_progress_count,
            "critical_tickets": critical_count,
            "pending_tickets": pending_count,
            "resolved_tickets": resolved_count,
            "teams_breakdown": [{"name": t.name, "tickets": t.ticket_count} for t in teams],
            "total_conversations": total_conversations,
            "escalated_conversations": escalated_conversations,
            "ai_runs": total_agent_runs,
            "ai_success_rate": ai_success_rate,
        }

metrics_service = MetricsService()

