import time
import logging
from apps.conversations.models import Conversation, Message
from apps.tickets.models import Ticket, TicketEvent
from apps.ai_engine.models import AgentRun
from services.ai.llm_service import llm_service
from services.ai.tool_registry import tool_registry

logger = logging.getLogger(__name__)

class AgentRunner:
    """Orchestrates conversations, intent evaluation, RAG retrieval, and immediate escalation."""

    @classmethod
    def handle_customer_message(cls, conversation: Conversation, customer_text: str) -> dict:
        workspace = conversation.workspace
        start_time = time.time()

        # 1. Save customer message
        Message.objects.create(
            conversation=conversation,
            sender_type=Message.SenderType.CUSTOMER,
            content=customer_text
        )

        # 2. Classify intent, sentiment, and urgency
        classification = llm_service.classify_intent_urgency(customer_text)
        conversation.intent = classification["intent"]
        conversation.sentiment = classification["sentiment"]
        if classification["urgency"] == "CRITICAL" or conversation.urgency != "CRITICAL":
            conversation.urgency = classification["urgency"]

        # 3. Check for immediate escalation
        escalation_result = None
        if classification["is_escalated"] or classification["urgency"] == "CRITICAL":
            conversation.is_escalated = True
            escalation_result = tool_registry.escalate_to_human(
                workspace_id=workspace.id,
                conversation_id=conversation.id,
                reason=f"Urgent Customer Query: {customer_text[:100]}"
            )

        conversation.save(update_fields=["intent", "sentiment", "urgency", "is_escalated", "updated_at"])

        # 4. Generate AI response
        # Authoritative Escalation Override: When an urgent escalation ticket is raised, guarantee the response mentions the ticket and SLA
        if escalation_result and escalation_result.get("ticket_number"):
            ticket_num = escalation_result["ticket_number"]
            team_name = escalation_result.get("assigned_team") or "Billing Support"
            sla_mins = getattr(getattr(workspace, "settings", None), "sla_urgent_minutes", 15)
            ai_response_text = (
                f"I have marked this as urgent and immediately routed it to our {team_name} team. "
                f"Your support ticket is #{ticket_num}. A dedicated human specialist will review your case and respond within {sla_mins} minutes."
            )
            ai_result = {
                "text": ai_response_text,
                "source": "urgent_escalation_protocol",
                "tokens_used": len(ai_response_text.split()),
                "retrieved_docs": []
            }
        else:
            history = list(conversation.messages.values("sender_type", "content"))
            customer_email = conversation.customer.email if conversation.customer else None
            ai_result = llm_service.generate_response(workspace, customer_text, history, customer_email=customer_email)
            ai_response_text = ai_result["text"]

        # 5. Save AI message
        ai_msg = Message.objects.create(
            conversation=conversation,
            sender_type=Message.SenderType.AI,
            content=ai_response_text,
            metadata={"source": ai_result["source"], "docs_count": len(ai_result.get("retrieved_docs", []))}
        )

        # 6. Log Agent Run
        latency = int((time.time() - start_time) * 1000)
        AgentRun.objects.create(
            workspace=workspace,
            conversation=conversation,
            run_type=AgentRun.RunType.CHAT,
            input_prompt=customer_text,
            output_response=ai_response_text,
            tokens_used=ai_result.get("tokens_used", 0),
            latency_ms=latency,
            success=True
        )

        return {
            "ai_message": ai_msg.content,
            "conversation_id": conversation.id,
            "intent": conversation.intent,
            "urgency": conversation.urgency,
            "is_escalated": conversation.is_escalated,
            "escalation_ticket": escalation_result.get("ticket_number") if escalation_result else None
        }

agent_runner = AgentRunner()
