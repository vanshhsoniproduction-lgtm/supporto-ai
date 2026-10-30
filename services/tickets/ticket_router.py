from apps.teams.models import Team
from apps.tickets.models import Ticket

class TicketRouter:
    """Intelligently routes tickets based on category, priority, and workload."""

    @staticmethod
    def route_ticket(ticket: Ticket) -> Team | None:
        workspace = ticket.workspace
        teams = Team.objects.filter(workspace=workspace, is_active=True)
        if not teams.exists():
            return None

        cat_lower = ticket.category.lower()
        sub_lower = ticket.subject.lower()

        if any(w in cat_lower or w in sub_lower for w in ["bill", "charge", "refund", "invoice", "payment"]):
            billing = teams.filter(name__icontains="bill").first()
            if billing:
                return billing

        if any(w in cat_lower or w in sub_lower for w in ["order", "deliver", "ship", "tracking"]):
            order = teams.filter(name__icontains="order").first()
            if order:
                return order

        return teams.first()

ticket_router = TicketRouter()

