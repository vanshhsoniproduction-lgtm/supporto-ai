import re
import json
import logging
from apps.ai_engine.models import AgentConfiguration
from apps.teams.models import Team
from services.ai.model_manager import model_manager
from services.ai.rag_service import rag_service
from services.ai.prompt_builder import prompt_builder

logger = logging.getLogger(__name__)

class LLMService:
    """
    LLM Inference Service for Supporto AI.
    Integrates with local Qwen 8B GGUF model when llama-cpp-python is available,
    with an intelligent fallback engine for high reliability.
    """

    @classmethod
    def generate_response(cls, workspace, customer_message: str, message_history: list[dict] = None) -> dict:
        if message_history is None:
            message_history = []

        config, _ = AgentConfiguration.objects.get_or_create(workspace=workspace)
        system_prompt = config.system_prompt
        retrieved = rag_service.retrieve_context(workspace.id, customer_message, top_k=3)

        llm = model_manager.get_llm()
        if llm:
            try:
                prompt = prompt_builder.build_chat_prompt(
                    system_prompt=system_prompt,
                    company_name=workspace.name,
                    retrieved_context=retrieved,
                    message_history=message_history,
                    customer_message=customer_message,
                )
                output = llm(
                    prompt,
                    max_tokens=config.max_tokens,
                    temperature=config.temperature,
                    stop=["<|im_end|>", "<|endoftext|>"]
                )
                text = output["choices"][0]["text"].strip()
                tokens = output.get("usage", {}).get("total_tokens", 0)
                return {
                    "text": text,
                    "retrieved_docs": retrieved,
                    "tokens_used": tokens,
                    "source": "qwen_local_llm"
                }
            except Exception as e:
                logger.error(f"Error executing Qwen inference: {e}")

        # Intelligent RAG-grounded fallback response generator
        response_text = cls._generate_grounded_fallback(workspace, customer_message, retrieved)
        return {
            "text": response_text,
            "retrieved_docs": retrieved,
            "tokens_used": len(response_text.split()),
            "source": "supporto_rag_engine"
        }

    @staticmethod
    def _generate_grounded_fallback(workspace, message: str, retrieved_docs: list[dict]) -> str:
        msg_lower = message.lower()

        # Urgent pattern detection
        urgent_keywords = ["deducted twice", "double charged", "charged twice", "unauthorized charge", "fraud", "scam", "overcharged", "money stolen"]
        if any(k in msg_lower for k in urgent_keywords):
            return (
                f"I understand you are reporting an urgent billing concern ({message.strip()}). "
                f"I have flagged this as critical and escalated your case directly to our Billing Support team. "
                "A specialist is reviewing your account immediately."
            )

        if retrieved_docs:
            top_doc = retrieved_docs[0]
            answer = top_doc.get("content", "")
            return f"Based on {workspace.name}'s support documentation for '{top_doc['title']}':\n\n{answer}\n\nDoes this resolve your question?"

        if any(w in msg_lower for w in ["hello", "hi", "hey", "help"]):
            return f"Hello! Welcome to {workspace.name} customer support. How can I help you today?"

        return (
            f"Thank you for contacting {workspace.name}. I have logged your inquiry: '{message[:80]}...'. "
            "Our support team has received your ticket and will assist you shortly."
        )

    @classmethod
    def classify_intent_urgency(cls, text: str) -> dict:
        """Classifies intent, sentiment, and urgency."""
        t_lower = text.lower()

        # Urgency & Escalation check
        critical_terms = ["deducted twice", "double charge", "charged twice", "unauthorized", "legal", "urgent", "stolen", "lawyer", "refund immediately"]
        high_terms = ["broken", "not working", "fail", "error", "damaged", "wrong item", "cancel order"]

        urgency = "LOW"
        is_escalated = False

        if any(term in t_lower for term in critical_terms):
            urgency = "CRITICAL"
            is_escalated = True
        elif any(term in t_lower for term in high_terms):
            urgency = "HIGH"

        # Sentiment check
        if any(term in t_lower for term in ["angry", "horrible", "worst", "terrible", "hate", "scam", "cheat"]):
            sentiment = "FRUSTRATED"
        elif any(term in t_lower for term in ["bad", "wrong", "disappointed", "problem", "issue"]):
            sentiment = "NEGATIVE"
        elif any(term in t_lower for term in ["great", "thank", "awesome", "good", "solved", "love"]):
            sentiment = "POSITIVE"
        else:
            sentiment = "NEUTRAL"

        # Intent
        if any(term in t_lower for term in ["bill", "charge", "payment", "invoice", "refund", "receipt"]):
            intent = "Billing & Payments"
        elif any(term in t_lower for term in ["order", "track", "delivery", "shipping", "package", "arrival"]):
            intent = "Order Tracking & Delivery"
        elif any(term in t_lower for term in ["return", "exchange", "replace"]):
            intent = "Returns & Exchanges"
        elif any(term in t_lower for term in ["login", "password", "account", "profile"]):
            intent = "Account & Access"
        else:
            intent = "General Inquiry"

        return {
            "intent": intent,
            "sentiment": sentiment,
            "urgency": urgency,
            "is_escalated": is_escalated
        }

    @classmethod
    def recommend_team_routing(cls, workspace, intent_or_text: str):
        """Matches intent or inquiry to the best team in the workspace."""
        text_lower = intent_or_text.lower()
        teams = Team.objects.filter(workspace=workspace, is_active=True)

        if any(w in text_lower for w in ["bill", "payment", "charge", "refund", "invoice"]):
            billing_team = teams.filter(name__icontains="bill").first()
            if billing_team:
                return billing_team

        if any(w in text_lower for w in ["order", "deliver", "ship", "tracking", "package"]):
            order_team = teams.filter(name__icontains="order").first()
            if order_team:
                return order_team

        if any(w in text_lower for w in ["tech", "bug", "code", "crash", "api"]):
            tech_team = teams.filter(name__icontains="tech").first()
            if tech_team:
                return tech_team

        return teams.first()

    @classmethod
    def summarize_conversation(cls, messages: list[dict]) -> str:
        """Summarizes conversation transcript."""
        if not messages:
            return "No conversation history available."
        customer_msgs = [m["content"] for m in messages if m.get("sender_type") == "CUSTOMER"]
        if not customer_msgs:
            return "Customer initiated contact with no follow-up queries."
        first_issue = customer_msgs[0][:150]
        total_turns = len(messages)
        return f"Customer inquiry regarding: '{first_issue}'. Total interaction turns: {total_turns}."

llm_service = LLMService()

