import csv
import io
from datetime import timedelta
from django.utils import timezone
from django.db.models import Count
from apps.emails.models import InboundEmail, TicketProposal
from apps.conversations.models import Conversation, Message
from apps.tickets.models import Ticket
from apps.teams.models import Team

class WeeklyInsightsService:
    @classmethod
    def get_weekly_report(cls, workspace) -> dict:
        """
        Calculates factual weekly metrics (last 7 days) for the workspace.
        Never fabricates trends or numbers.
        """
        now = timezone.now()
        start_date = now - timedelta(days=7)

        # 1. Emails
        emails_qs = InboundEmail.objects.filter(workspace=workspace, received_at__gte=start_date)
        total_emails = emails_qs.count()

        # 2. Conversations
        convs_qs = Conversation.objects.filter(workspace=workspace, created_at__gte=start_date)
        total_conversations = convs_qs.count()

        # 3. Proposals & Approval status
        proposals_qs = TicketProposal.objects.filter(workspace=workspace, created_at__gte=start_date)
        tickets_proposed = proposals_qs.count()
        tickets_approved = proposals_qs.filter(approval_status=TicketProposal.ApprovalStatus.APPROVED).count()
        tickets_rejected = proposals_qs.filter(approval_status=TicketProposal.ApprovalStatus.REJECTED).count()

        # 4. Tickets (all channels)
        tickets_qs = Ticket.objects.filter(workspace=workspace, created_at__gte=start_date)
        total_tickets = tickets_qs.count()
        unresolved_tickets = Ticket.objects.filter(
            workspace=workspace,
            status__in=[Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS, Ticket.Status.PENDING]
        ).count()

        # Ticket Categories & Percentages
        category_counts = list(
            tickets_qs.values("category")
            .annotate(count=Count("id"))
            .order_by("-count")
        )

        recurring_complaints = []
        for cat_info in category_counts:
            pct = round((cat_info["count"] / total_tickets) * 100, 1) if total_tickets > 0 else 0
            cat_info["percentage"] = pct

            # Gather sample quotes from tickets or emails in this category
            quotes = list(
                tickets_qs.filter(category=cat_info["category"])
                .exclude(description="")
                .values_list("description", flat=True)[:2]
            )
            clean_quotes = [q.strip()[:140] for q in quotes if q and q.strip()]

            recurring_complaints.append({
                "category": cat_info["category"],
                "count": cat_info["count"],
                "percentage": pct,
                "sample_quotes": clean_quotes,
            })

        # Urgent issues
        urgent_tickets = tickets_qs.filter(priority__in=[Ticket.Priority.HIGH, Ticket.Priority.CRITICAL]).count()
        urgent_emails = emails_qs.filter(proposal__ai_urgency__in=["HIGH", "CRITICAL"]).count()
        total_urgent = max(urgent_tickets, urgent_emails)

        # 5. Sentiment Distribution
        sentiments = {"POSITIVE": 0, "NEUTRAL": 0, "NEGATIVE": 0, "FRUSTRATED": 0, "ANGRY": 0}
        for c in convs_qs.values("sentiment").annotate(count=Count("id")):
            s = c["sentiment"]
            if s in sentiments:
                sentiments[s] += c["count"]

        # Also pull from proposals
        for p in proposals_qs.values("ai_sentiment").annotate(count=Count("id")):
            s = p["ai_sentiment"]
            if s in sentiments:
                sentiments[s] += p["count"]

        total_sentiment_events = sum(sentiments.values())

        # 6. Team Workload
        team_workload = []
        for team in Team.objects.filter(workspace=workspace, is_active=True):
            assigned_count = Ticket.objects.filter(workspace=workspace, assigned_team=team, created_at__gte=start_date).count()
            open_count = Ticket.objects.filter(
                workspace=workspace,
                assigned_team=team,
                status__in=[Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS]
            ).count()
            team_workload.append({
                "team_name": team.name,
                "assigned_this_week": assigned_count,
                "active_backlog": open_count,
            })

        # 7. Resolution Time
        resolved_tickets = Ticket.objects.filter(
            workspace=workspace,
            resolved_at__isnull=False,
            created_at__gte=start_date
        )
        avg_res_hours = 0.0
        if resolved_tickets.exists():
            durations = []
            for t in resolved_tickets:
                if t.resolved_at and t.created_at:
                    diff = (t.resolved_at - t.created_at).total_seconds() / 3600.0
                    durations.append(diff)
            if durations:
                avg_res_hours = round(sum(durations) / len(durations), 1)

        # 8. AI-assisted response count
        ai_messages = Message.objects.filter(
            conversation__workspace=workspace,
            sender_type=Message.SenderType.AI,
            created_at__gte=start_date
        ).count()
        ai_reply_drafts = proposals_qs.exclude(ai_suggested_reply="").count()
        total_ai_assisted = ai_messages + ai_reply_drafts

        # 9. Most common customer complaint topics from proposals
        complaint_topics = list(
            proposals_qs.values("ai_intent")
            .annotate(count=Count("id"))
            .order_by("-count")[:5]
        )

        # 10. Generate Grounded AI Written Summary
        summary = cls._generate_written_summary(
            workspace=workspace,
            total_emails=total_emails,
            total_conversations=total_conversations,
            total_tickets=total_tickets,
            tickets_approved=tickets_approved,
            total_urgent=total_urgent,
            sentiments=sentiments,
            top_category=category_counts[0]["category"] if category_counts else "General Support",
            avg_res_hours=avg_res_hours
        )

        return {
            "period": f"{start_date.strftime('%b %d, %Y')} - {now.strftime('%b %d, %Y')}",
            "total_emails": total_emails,
            "total_conversations": total_conversations,
            "total_tickets": total_tickets,
            "tickets_proposed": tickets_proposed,
            "tickets_approved": tickets_approved,
            "tickets_rejected": tickets_rejected,
            "unresolved_tickets": unresolved_tickets,
            "urgent_count": total_urgent,
            "category_counts": category_counts,
            "recurring_complaints": recurring_complaints,
            "sentiments": sentiments,
            "total_sentiment_events": total_sentiment_events,
            "team_workload": team_workload,
            "avg_resolution_hours": avg_res_hours,
            "ai_assisted_count": total_ai_assisted,
            "complaint_topics": complaint_topics,
            "summary_text": summary,
        }

    @staticmethod
    def _generate_written_summary(workspace, total_emails, total_conversations, total_tickets, tickets_approved, total_urgent, sentiments, top_category, avg_res_hours) -> str:
        total_interactions = total_emails + total_conversations
        if total_interactions == 0 and total_tickets == 0:
            return (
                f"No customer interactions or tickets were recorded for {workspace.name} over the past 7 days. "
                "Once incoming emails, chat conversations, or voice sessions are initiated, real-time weekly metrics and trends will be automatically analyzed here."
            )

        pos_count = sentiments.get("POSITIVE", 0)
        neg_count = sentiments.get("NEGATIVE", 0) + sentiments.get("FRUSTRATED", 0) + sentiments.get("ANGRY", 0)

        sentiment_note = "customer sentiment was predominantly neutral or balanced"
        if pos_count > neg_count and pos_count > 0:
            sentiment_note = f"customer sentiment was predominantly positive ({pos_count} positive signals)"
        elif neg_count > pos_count:
            sentiment_note = f"customer sentiment reflected notable friction ({neg_count} negative/frustrated signals requiring attention)"

        return (
            f"Over the past 7 days, {workspace.name} handled a total of {total_interactions} customer interactions "
            f"({total_emails} incoming emails and {total_conversations} customer live chat sessions). "
            f"A total of {total_tickets} support tickets were managed, with {tickets_approved} ticket proposals formally approved by support staff. "
            f"The primary driver of customer inquiries was '{top_category}'. "
            f"Overall {sentiment_note}. "
            f"{total_urgent} high or critical urgency issues were identified and routed through human review. "
            f"Average resolution time across resolved tickets currently stands at {avg_res_hours} hours."
        )

    @classmethod
    def export_csv(cls, report: dict) -> str:
        """Generates a CSV string representation of the weekly report."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Metric", "Value"])
        writer.writerow(["Reporting Period", report["period"]])
        writer.writerow(["Total Incoming Emails", report["total_emails"]])
        writer.writerow(["Total Customer Conversations", report["total_conversations"]])
        writer.writerow(["Total Tickets Generated", report["total_tickets"]])
        writer.writerow(["Tickets Approved by Staff", report["tickets_approved"]])
        writer.writerow(["Tickets Rejected by Staff", report["tickets_rejected"]])
        writer.writerow(["Unresolved Tickets (Backlog)", report["unresolved_tickets"]])
        writer.writerow(["High/Critical Urgency Issues", report["urgent_count"]])
        writer.writerow(["Average Resolution Hours", report["avg_resolution_hours"]])
        writer.writerow(["AI-Assisted Operations", report["ai_assisted_count"]])
        writer.writerow([])
        writer.writerow(["Category", "Count", "Percentage (%)"])
        for c in report.get("category_counts", []):
            writer.writerow([c.get("category"), c.get("count"), f"{c.get('percentage', 0)}%"])
        writer.writerow([])
        writer.writerow(["Sentiment", "Count"])
        for k, v in report["sentiments"].items():
            writer.writerow([k, v])
        writer.writerow([])
        writer.writerow(["Team", "Assigned This Week", "Active Backlog"])
        for tw in report["team_workload"]:
            writer.writerow([tw["team_name"], tw["assigned_this_week"], tw["active_backlog"]])
        return output.getvalue()

weekly_insights_service = WeeklyInsightsService()
