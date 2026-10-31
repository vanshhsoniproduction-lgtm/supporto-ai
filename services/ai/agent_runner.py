import time
import logging
from apps.conversations.models import Conversation, Message
from apps.tickets.models import Ticket, TicketEvent
from apps.teams.models import Team
from apps.ai_engine.models import AgentRun
from services.ai.llm_service import llm_service, extract_order_code
from services.ai.tool_registry import tool_registry

logger = logging.getLogger(__name__)

class AgentRunner:
    """Orchestrates conversations, intent evaluation, tool calling, and human escalation."""

    @classmethod
    def handle_customer_message(cls, conversation: Conversation, customer_text: str) -> dict:
        workspace = conversation.workspace
        start_time = time.time()

        # 1. Save incoming customer message
        Message.objects.create(
            conversation=conversation,
            sender_type=Message.SenderType.CUSTOMER,
            content=customer_text
        )

        # 2. Classify intent, sentiment, and urgency
        classification = llm_service.classify_intent_urgency(customer_text)

        # Check if customer is responding affirmatively to an offer to connect with human support
        last_ai_msg = conversation.messages.filter(sender_type=Message.SenderType.AI).order_by("-id").first()
        is_handoff_confirmation = False
        if last_ai_msg and any(phrase in last_ai_msg.content.lower() for phrase in ["connect you with a member", "connect you with our support team", "connect you with our human", "connect you with a human"]):
            if any(w in customer_text.lower().strip() for w in ["yes", "yes please", "sure", "connect me", "yeah", "ok connect", "please connect", "do that"]):
                is_handoff_confirmation = True
                classification["is_escalated"] = True
                classification["urgency"] = "HIGH"
                classification["intent"] = "HUMAN_HANDOFF"

        # Save conversation with fresh signals before escalation
        conversation.intent = classification["intent"]
        conversation.sentiment = classification["sentiment"]
        if classification["urgency"] == "CRITICAL" or conversation.urgency != "CRITICAL":
            conversation.urgency = classification["urgency"]
        conversation.save(update_fields=["intent", "sentiment", "urgency", "updated_at"])

        # 3. Check for immediate escalation
        escalation_result = None
        if classification["is_escalated"] or classification["urgency"] == "CRITICAL":
            conversation.is_escalated = True
            conversation.save(update_fields=["is_escalated", "updated_at"])
            escalation_result = tool_registry.escalate_to_human(
                workspace_id=workspace.id,
                conversation_id=conversation.id,
                reason=customer_text[:120],
                customer_message=customer_text
            )

        # 4. Generate AI response
        # Authoritative Escalation Override: When an urgent escalation ticket is raised, guarantee ticket and SLA in response
        if escalation_result and escalation_result.get("ticket_number"):
            ticket_num = escalation_result["ticket_number"]
            team_name = escalation_result.get("assigned_team") or "Support Team"
            sla_mins = getattr(getattr(workspace, "settings", None), "sla_urgent_minutes", 15)

            if is_handoff_confirmation or classification.get("intent") == "HUMAN_HANDOFF":
                ai_response_text = (
                    f"I've connected you with our {team_name} team. Your support ticket is #{ticket_num}. "
                    f"A human specialist will review your inquiry and assist you within {sla_mins} minutes."
                )
            else:
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
            customer_email = (conversation.customer.email if conversation.customer else None) or conversation.metadata.get("customer_email")
            customer_phone = (conversation.customer.normalized_phone if conversation.customer else None) or (conversation.customer.phone if conversation.customer else None) or conversation.metadata.get("customer_phone")
            ai_result = llm_service.generate_response(
                workspace=workspace,
                customer_message=customer_text,
                message_history=history,
                customer_email=customer_email,
                customer_phone=customer_phone
            )
            ai_response_text = ai_result["text"]

        # 5. Save AI message
        ai_msg = Message.objects.create(
            conversation=conversation,
            sender_type=Message.SenderType.AI,
            content=ai_response_text,
            metadata={"source": ai_result["source"], "docs_count": len(ai_result.get("retrieved_docs", []))}
        )

        # 6. Log Agent Run & Audit Tool Execution
        latency = int((time.time() - start_time) * 1000)
        run_record = AgentRun.objects.create(
            workspace=workspace,
            conversation=conversation,
            run_type=AgentRun.RunType.CHAT,
            input_prompt=customer_text,
            output_response=ai_response_text,
            tokens_used=ai_result.get("tokens_used", 0),
            latency_ms=latency,
            success=True
        )

        # Audit tools in ToolExecution
        extracted_code = extract_order_code(customer_text)
        customer_phone = (conversation.customer.normalized_phone if conversation.customer else None) or conversation.metadata.get("customer_phone")
        if extracted_code:
            tool_registry.execute_tool(
                workspace_id=workspace.id,
                tool_name="lookup_order",
                arguments={"order_number": extracted_code, "phone": customer_phone or ""},
                customer_id=conversation.customer.id if conversation.customer else None,
                conversation_id=conversation.id,
                agent_run=run_record
            )

        if escalation_result:
            tool_registry.execute_tool(
                workspace_id=workspace.id,
                tool_name="escalate_to_human",
                arguments={"reason": customer_text[:100]},
                customer_id=conversation.customer.id if conversation.customer else None,
                conversation_id=conversation.id,
                agent_run=run_record
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
