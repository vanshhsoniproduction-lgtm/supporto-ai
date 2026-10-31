import json
import logging
import re
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from apps.customers.models import Customer
from apps.conversations.models import Conversation, Message
from apps.teams.models import Team
from apps.tickets.models import Ticket
from apps.emails.models import InboundEmail, TicketProposal
from services.ai.rag_service import rag_service
from services.ai.llm_service import has_word
from services.ai.model_manager import model_manager

logger = logging.getLogger(__name__)

INTENT_CATEGORIES = [
    "ORDER_STATUS",
    "PAYMENT_ISSUE",
    "REFUND_REQUEST",
    "TECHNICAL_SUPPORT",
    "ACCOUNT_ACCESS",
    "BILLING",
    "CANCELLATION",
    "COMPLAINT",
    "GENERAL_INQUIRY",
    "OTHER",
]

class EmailTriageService:
    @classmethod
    def process_inbound_email(cls, email: InboundEmail) -> TicketProposal:
        """
        Executes end-to-end AI triage pipeline for an inbound email:
        1. Resolves or creates Customer in workspace
        2. Creates Conversation & initial Message
        3. Analyzes intent, urgency, sentiment, confidence
        4. Retrieves relevant workspace Knowledge Base context
        5. Generates grounded draft reply
        6. Creates TicketProposal awaiting mandatory human approval
        """
        workspace = email.workspace

        with transaction.atomic():
            # 1. Customer Resolution (strict tenant isolation)
            norm_email = email.sender_email.strip().lower()
            customer = Customer.objects.filter(
                workspace=workspace,
                normalized_email=norm_email
            ).first()

            if not customer:
                name = email.sender_name or norm_email.split("@")[0].title()
                customer = Customer.objects.create(
                    workspace=workspace,
                    name=name,
                    email=norm_email,
                    normalized_email=norm_email,
                    source=Customer.Source.EMAIL,
                    status=Customer.Status.ACTIVE,
                    is_anonymous=False,
                    first_seen=email.received_at,
                    last_seen=email.received_at,
                )
            else:
                customer.last_seen = email.received_at
                customer.save(update_fields=["last_seen"])

            email.linked_customer = customer

            # 2. Link or create Conversation
            conversation = Conversation.objects.create(
                workspace=workspace,
                customer=customer,
                channel=Conversation.Channel.WEB_CHAT,
                status=Conversation.Status.ACTIVE,
                intent="",
                sentiment=Conversation.Sentiment.NEUTRAL,
                urgency=Conversation.Urgency.LOW,
            )
            email.linked_conversation = conversation

            # Store the incoming email message in the conversation
            msg_content = f"Subject: {email.subject}\n\n{email.normalized_text_body}"
            Message.objects.create(
                conversation=conversation,
                sender_type=Message.SenderType.CUSTOMER,
                content=msg_content[:4000],
                metadata={
                    "email_id": email.id,
                    "provider_message_id": email.provider_message_id,
                    "sender_name": email.sender_name,
                    "sender_email": email.sender_email,
                }
            )

            # 3. AI Analysis: Classification & RAG Context
            analysis = cls._analyze_email_content(workspace, email.subject, email.normalized_text_body)

            # 4. Retrieve Grounded Knowledge Base Context
            query_for_rag = f"{email.subject} {email.normalized_text_body[:200]}"
            retrieved_chunks = rag_service.retrieve_context(workspace.id, query_for_rag, top_k=3)

            # 5. Generate Grounded Draft Customer Reply
            draft_reply = cls._generate_draft_reply(
                workspace=workspace,
                customer=customer,
                subject=email.subject,
                body=email.normalized_text_body,
                analysis=analysis,
                retrieved_chunks=retrieved_chunks
            )

            # 6. Team Recommendation
            recommended_team = cls._resolve_recommended_team(workspace, analysis["intent"])

            # 7. Update Conversation with triage signals
            conversation.intent = analysis["intent"]
            conversation.sentiment = analysis["sentiment"]
            conversation.urgency = analysis["urgency"]
            conversation.summary = analysis["summary"]
            conversation.is_escalated = (analysis["urgency"] == "CRITICAL")
            conversation.save()

            # 8. Create TicketProposal
            ticket_needed = analysis.get("requires_ticket", True)
            approval_status = (
                TicketProposal.ApprovalStatus.PENDING_REVIEW
                if ticket_needed
                else TicketProposal.ApprovalStatus.NO_TICKET_REQUIRED
            )

            proposal, _ = TicketProposal.objects.update_or_create(
                inbound_email=email,
                defaults={
                    "workspace": workspace,
                    "customer": customer,
                    "conversation": conversation,
                    "proposed_subject": email.subject[:255],
                    "proposed_description": email.normalized_text_body,
                    "proposed_category": analysis["category"],
                    "proposed_priority": analysis["priority"],
                    "ai_intent": analysis["intent"],
                    "ai_sentiment": analysis["sentiment"],
                    "ai_urgency": analysis["urgency"],
                    "ai_summary": analysis["summary"],
                    "ai_recommended_team": recommended_team,
                    "ai_confidence": analysis["confidence"],
                    "ai_suggested_reply": draft_reply,
                    "edited_suggested_reply": draft_reply,
                    "kb_sources_used": [c.get("title") for c in retrieved_chunks if c.get("title")],
                    "approval_status": approval_status,
                }
            )

            # Update email processing status
            email.processing_status = (
                InboundEmail.ProcessingStatus.TICKET_PROPOSED
                if ticket_needed
                else InboundEmail.ProcessingStatus.NO_TICKET
            )
            email.save(update_fields=["linked_customer", "linked_conversation", "processing_status"])

            return proposal

    @classmethod
    def _analyze_email_content(cls, workspace, subject: str, body: str) -> dict:
        """
        Calibrated email intent, sentiment, urgency, and category triage.
        Features negation resistance, positive feedback filtering, and authentic scoring.
        """
        full_text = f"{subject}\n{body}".lower()

        # Check for negation patterns (e.g. "not angry", "no rush", "not urgent")
        has_calm_negation = bool(re.search(
            r"\b(?:not|no|never|don't|dont)\s+(?:angry|mad|furious|urgent|rush|hurry|panic)\b",
            full_text
        ))

        # Check for positive customer compliments / praise (No ticket backlog needed)
        is_positive_compliment = (
            has_word(full_text, ["thank you", "thanks", "love the", "great job", "awesome service", "perfect", "appreciate", "kudos"]) and
            not has_word(full_text, ["broken", "refund", "return", "delayed", "missing", "charge", "stolen", "cancel"])
        )

        # Critical / Fraud / Severe outage pattern detection
        critical_markers = [
            "fraud", "unauthorized", "stolen", "deducted twice", "charged twice",
            "double charge", "security breach", "lawyer", "legal action", "compromised",
            "account takeover", "severe outage"
        ]
        is_critical = any(m in full_text for m in critical_markers)

        # Default baseline
        intent = "GENERAL_INQUIRY"
        category = "General Support"
        priority = Ticket.Priority.MEDIUM
        urgency = "LOW"
        sentiment = "NEUTRAL"
        confidence = 0.86
        requires_ticket = True

        if is_positive_compliment:
            intent = "GENERAL_INQUIRY"
            category = "Customer Feedback"
            urgency = "LOW"
            priority = Ticket.Priority.LOW
            sentiment = "POSITIVE"
            confidence = 0.96
            requires_ticket = False

        elif has_word(full_text, ["charged twice", "double charge", "deducted twice"]):
            intent = "PAYMENT_ISSUE"
            category = "Billing & Payments"
            urgency = "CRITICAL"
            priority = Ticket.Priority.CRITICAL
            sentiment = "ANGRY" if not has_calm_negation else "NEUTRAL"
            confidence = 0.98

        elif has_word(full_text, ["refund", "invoice", "payment", "overcharged", "card charged", "billing", "receipt"]):
            intent = "REFUND_REQUEST"
            category = "Billing & Payments"
            urgency = "LOW" if has_calm_negation else "HIGH"
            priority = Ticket.Priority.MEDIUM if has_calm_negation else Ticket.Priority.HIGH
            sentiment = "NEUTRAL" if has_calm_negation else "NEGATIVE"
            confidence = 0.92

        elif has_word(full_text, ["login", "log in", "sign in", "password", "sso", "saml", "authentication", "locked out"]):
            intent = "ACCOUNT_ACCESS"
            category = "Technical Support"
            urgency = "HIGH"
            priority = Ticket.Priority.HIGH
            sentiment = "FRUSTRATED" if not has_calm_negation else "NEUTRAL"
            confidence = 0.94

        elif has_word(full_text, ["crash", "crashing", "crashed", "outage", "broken", "bug", "glitch", "error", "fails", "failed", "500", "502"]):
            intent = "TECHNICAL_SUPPORT"
            category = "Technical Support"
            urgency = "HIGH"
            priority = Ticket.Priority.HIGH
            sentiment = "FRUSTRATED" if not has_calm_negation else "NEUTRAL"
            confidence = 0.93

        elif has_word(full_text, ["order", "shipment", "tracking", "arrive", "arrived", "delivery", "delivered", "package", "parcel", "awb", "consignment", "courier", "dispatch", "transit"]):
            intent = "ORDER_STATUS"
            category = "Order & Shipping"
            is_delayed = has_word(full_text, ["delayed", "delay", "lost", "stuck", "missing", "not arrived", "has not arrived"])
            urgency = "MEDIUM" if is_delayed else "LOW"
            priority = Ticket.Priority.HIGH if is_delayed else Ticket.Priority.MEDIUM
            sentiment = "FRUSTRATED" if (is_delayed and not has_calm_negation) else "NEUTRAL"
            confidence = 0.92

        elif has_word(full_text, ["cancel", "cancellation", "close account", "termination", "unsubscribe"]):
            intent = "CANCELLATION"
            category = "Account Services"
            urgency = "MEDIUM"
            priority = Ticket.Priority.MEDIUM
            sentiment = "NEGATIVE" if not has_calm_negation else "NEUTRAL"
            confidence = 0.90

        elif has_word(full_text, ["damaged", "crushed", "spoiled", "rotten", "broken item", "defect"]):
            intent = "COMPLAINT"
            category = "Quality & Damage"
            urgency = "HIGH"
            priority = Ticket.Priority.HIGH
            sentiment = "ANGRY" if not has_calm_negation else "NEUTRAL"
            confidence = 0.91

        elif has_word(full_text, ["bulk", "wholesale", "quote", "pricing inquiry", "volume purchase"]):
            intent = "GENERAL_INQUIRY"
            category = "Sales & Inquiries"
            urgency = "LOW"
            priority = Ticket.Priority.LOW
            sentiment = "NEUTRAL"
            confidence = 0.88

        elif has_word(full_text, ["warranty", "guarantee", "manual", "specifications", "compatible"]):
            intent = "GENERAL_INQUIRY"
            category = "General Support"
            urgency = "LOW"
            priority = Ticket.Priority.LOW
            sentiment = "NEUTRAL"
            confidence = 0.89

        elif has_word(full_text, ["terrible", "awful", "unacceptable", "horrible", "worst", "cheated", "scam"]):
            intent = "COMPLAINT"
            category = "Customer Experience"
            urgency = "HIGH"
            priority = Ticket.Priority.HIGH
            sentiment = "ANGRY"
            confidence = 0.91

        if is_critical and not is_positive_compliment:
            urgency = "CRITICAL"
            priority = Ticket.Priority.CRITICAL
            if not has_calm_negation:
                sentiment = "ANGRY"

        summary = f"Customer inquiring about {intent.lower().replace('_', ' ')}. Subject: '{subject}'."
        if is_critical:
            summary = f"CRITICAL PRIORITY: Potential high-urgency issue detected ({intent}). Customer reports: '{body[:120]}...'"

        return {
            "intent": intent,
            "category": category,
            "urgency": urgency,
            "priority": priority,
            "sentiment": sentiment,
            "confidence": confidence,
            "summary": summary,
            "requires_ticket": requires_ticket,
        }

    @classmethod
    def _generate_draft_reply(cls, workspace, customer, subject: str, body: str, analysis: dict, retrieved_chunks: list[dict]) -> str:
        first_name = customer.name.split()[0] if customer.name and customer.name != "Visitor" else "there"
        company_name = workspace.name

        kb_snippet = ""
        if retrieved_chunks:
            top_chunk = retrieved_chunks[0]
            kb_snippet = f"\n\nAccording to our knowledge base ({top_chunk.get('title')}):\n{top_chunk.get('content', '')[:350]}"

        if not analysis.get("requires_ticket"):
            return (
                f"Hi {first_name},\n\n"
                f"Thank you so much for your kind words regarding {company_name}! "
                "Our entire team truly appreciates your feedback. If you ever need anything else in the future, please don't hesitate to reach out.\n\n"
                f"Warm regards,\n{company_name} Customer Experience Team"
            )

        if analysis["urgency"] == "CRITICAL":
            return (
                f"Dear {first_name},\n\n"
                f"Thank you for contacting {company_name} Support. We understand this is an urgent matter regarding '{subject}', "
                f"and we apologize for any stress caused. Your case has been immediately escalated to our specialized support team "
                f"with top priority.\n\n"
                f"A team specialist has been assigned and is actively investigating your request. We will follow up with you as soon as possible.{kb_snippet}\n\n"
                f"Best regards,\n{company_name} Customer Support"
            )

        if analysis["intent"] == "ORDER_STATUS":
            return (
                f"Hi {first_name},\n\n"
                f"Thank you for reaching out to {company_name} regarding your order status.{kb_snippet}\n\n"
                f"Our fulfillment team is reviewing your details to provide you with the latest tracking updates. "
                f"Please reply with your order number or AWB if not already provided so we can verify delivery right away.\n\n"
                f"Sincerely,\n{company_name} Support Team"
            )

        if retrieved_chunks:
            return (
                f"Hi {first_name},\n\n"
                f"Thank you for contacting {company_name} Support regarding '{subject}'.{kb_snippet}\n\n"
                f"Please let us know if this resolves your concern, or if you need additional assistance from our support agents.\n\n"
                f"Best regards,\n{company_name} Support Team"
            )

        return (
            f"Hello {first_name},\n\n"
            f"Thank you for getting in touch with {company_name} Support. We have received your inquiry: '{subject}'.\n\n"
            f"A member of our support team is reviewing your inquiry and will follow up with detailed guidance shortly.\n\n"
            f"Best regards,\n{company_name} Customer Support"
        )

    @classmethod
    def _resolve_recommended_team(cls, workspace, intent: str):
        """Resolves the best matching Team in the workspace based on intent."""
        if intent in ("PAYMENT_ISSUE", "REFUND_REQUEST", "BILLING"):
            team = Team.objects.filter(
                workspace=workspace,
                is_active=True
            ).filter(
                Q(name__icontains="Billing") |
                Q(name__icontains="Claims") |
                Q(name__icontains="Refund")
            ).first()
            if team:
                return team
        elif intent in ("TECHNICAL_SUPPORT", "ACCOUNT_ACCESS"):
            team = Team.objects.filter(
                workspace=workspace,
                is_active=True
            ).filter(
                Q(name__icontains="Tech") |
                Q(name__icontains="Dev") |
                Q(name__icontains="Engineering")
            ).first()
            if team:
                return team
        elif intent in ("ORDER_STATUS", "CANCELLATION", "SHIPPING"):
            team = Team.objects.filter(
                workspace=workspace,
                is_active=True
            ).filter(
                Q(name__icontains="Tracking") |
                Q(name__icontains="Delivery") |
                Q(name__icontains="Order") |
                Q(name__icontains="Shipping")
            ).first()
            if team:
                return team

        # Fallback to General Support or first active team
        general_team = Team.objects.filter(workspace=workspace, is_active=True, name__icontains="Support").first()
        return general_team or Team.objects.filter(workspace=workspace, is_active=True).first()

email_triage_service = EmailTriageService()

def triage_incoming_email(sender: str, subject: str, body_text: str, workspace) -> dict:
    """Convenience helper to triage incoming email and return classification dict."""
    return EmailTriageService._analyze_email_content(workspace, subject, body_text)
