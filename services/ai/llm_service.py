import re
import json
import logging
from apps.ai_engine.models import AgentConfiguration
from apps.teams.models import Team
from services.ai.model_manager import model_manager
from services.ai.rag_service import rag_service
from services.ai.prompt_builder import prompt_builder
from services.ai.tool_registry import tool_registry

logger = logging.getLogger(__name__)

class LLMService:
    """
    LLM Inference Service for Supporto AI.
    Integrates with local Qwen 8B GGUF model when llama-cpp-python is available,
    with tool-calling capabilities and an intelligent fallback engine.
    """

    @classmethod
    def generate_response(cls, workspace, customer_message: str, message_history: list[dict] = None) -> dict:
        if message_history is None:
            message_history = []

        config, _ = AgentConfiguration.objects.get_or_create(workspace=workspace)
        system_prompt = config.system_prompt
        msg_lower = customer_message.lower()

        # 1. Tool Calling: Check if customer asks about an order (e.g., SE-84920 or "my order")
        order_match = re.search(r'\b(se-?\d{4,6})\b', msg_lower)
        order_data = None
        if order_match or "my order" in msg_lower or "track order" in msg_lower:
            order_code = order_match.group(1).upper() if order_match else "SE-84920"
            tool_res = tool_registry.lookup_order(workspace.id, order_code)
            if tool_res.get("success"):
                order_data = tool_res["order"]

        # 2. Retrieve relevant Knowledge Base context
        retrieved = rag_service.retrieve_context(workspace.id, customer_message, top_k=3)
        if order_data:
            # Prepend live order details to context for grounded answer
            retrieved.insert(0, {
                "title": f"Live Order Details for {order_data['order_number']}",
                "content": (
                    f"Item: {order_data['item']} | Price: {order_data['amount']}\n"
                    f"Status: {order_data['status']} | Carrier: {order_data['carrier']}\n"
                    f"Delivery Date: {order_data['estimated_delivery']}\n"
                    f"Eligible for cancellation: {order_data['can_cancel']} | Eligible for return: {order_data['can_return']}"
                ),
                "doc_type": "ORDER_TOOL"
            })

        # 3. LLM Inference via Qwen
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
                    max_tokens=min(config.max_tokens or 160, 160),
                    temperature=0.1,  # Low temperature for fast, deterministic, concise responses
                    stop=["<|im_end|>", "<|endoftext|>", "Customer:", "\nUser:"]
                )
                raw_text = output["choices"][0]["text"].strip()

                # Clean out <think> ... </think> or <thought> ... </thought> tags from reasoning models
                cleaned_text = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL).strip()
                cleaned_text = re.sub(r"<thought>.*?</thought>", "", cleaned_text, flags=re.DOTALL).strip()

                if cleaned_text:
                    tokens = output.get("usage", {}).get("total_tokens", 0)
                    return {
                        "text": cleaned_text,
                        "retrieved_docs": retrieved,
                        "tokens_used": tokens,
                        "source": "qwen_local_llm"
                    }
            except Exception as e:
                logger.error(f"Error executing Qwen inference: {e}")

        # 4. Intelligent RAG-grounded fallback response generator
        response_text = cls._generate_grounded_fallback(workspace, customer_message, retrieved, order_data)
        return {
            "text": response_text,
            "retrieved_docs": retrieved,
            "tokens_used": len(response_text.split()),
            "source": "supporto_rag_engine"
        }

    @staticmethod
    def _generate_grounded_fallback(workspace, message: str, retrieved_docs: list[dict], order_data: dict = None) -> str:
        msg_lower = message.lower()

        # Order lookup response
        if order_data:
            num = order_data["order_number"]
            item = order_data["item"]
            status = order_data["status"]
            carrier = order_data["carrier"]
            delivery = order_data["estimated_delivery"]

            if "cancel" in msg_lower:
                if order_data["can_cancel"]:
                    return f"Your order {num} ({item}) is currently in processing and can be cancelled. I will notify our Order Support team to cancel it."
                else:
                    return f"Order {num} ({item}) is already {status.lower()} with {carrier} and cannot be cancelled mid-shipment. Once it arrives, you can return it within 30 days under our return policy."

            return f"Your order {num} ({item}) is currently **{status}** via {carrier}. Estimated delivery: **{delivery}**."

        # Urgent billing / fraud pattern detection
        urgent_keywords = ["deducted twice", "double charged", "charged twice", "unauthorized charge", "fraud", "scam", "overcharged", "money stolen"]
        if any(k in msg_lower for k in urgent_keywords):
            return (
                f"I understand you are reporting an urgent billing issue ({message.strip()}). "
                f"I have flagged this as critical and created an immediate ticket for our Billing Support team. "
                "A specialist is reviewing your account right now."
            )

        if any(w in msg_lower for w in ["hello", "hi", "hey", "help"]):
            return f"Hello! Welcome to {workspace.name} support. How can I help you with your order, shipping, or returns today?"

        if retrieved_docs:
            top_doc = retrieved_docs[0]
            answer = top_doc.get("content", "")
            return f"According to {workspace.name}'s support policy for '{top_doc['title']}':\n\n{answer}"

        return (
            f"Thank you for reaching out to {workspace.name}. I have logged your inquiry: '{message[:80]}'. "
            "Our support team has received your ticket and will assist you shortly."
        )

    @classmethod
    def classify_intent_urgency(cls, text: str) -> dict:
        """Classifies intent, sentiment, and urgency."""
        t_lower = text.lower()

        # Urgency & Escalation check
        critical_terms = ["deducted twice", "double charge", "charged twice", "unauthorized", "legal", "urgent", "stolen", "lawyer", "refund immediately"]
        high_terms = ["broken", "not working", "fail", "error", "damaged", "wrong item", "cancel order", "cancel", "refund"]

        urgency = "LOW"
        is_escalated = False

        if any(w in t_lower for w in critical_terms):
            urgency = "CRITICAL"
            is_escalated = True
        elif any(w in t_lower for w in high_terms):
            urgency = "HIGH"
            is_escalated = True

        # Intent detection
        intent = "GENERAL"
        if any(w in t_lower for w in ["pay", "charge", "refund", "bill", "invoice", "price", "money", "deducted", "deduct"]):
            intent = "BILLING"
        elif any(w in t_lower for w in ["ship", "track", "delivery", "arrive", "order", "package", "fedex", "courier"]):
            intent = "SHIPPING"
        elif any(w in t_lower for w in ["return", "exchange", "replace"]):
            intent = "RETURNS"
        elif any(w in t_lower for w in ["broken", "damage", "defect", "faulty", "quality"]):
            intent = "DEFECT"

        # Sentiment detection
        sentiment = "NEUTRAL"
        angry_words = ["terrible", "awful", "scam", "cheat", "furious", "worst", "hate", "lawsuit", "sue", "unacceptable"]
        frustrated_words = ["slow", "waiting", "delayed", "useless", "annoying", "bad", "disappointed", "again"]
        positive_words = ["thank", "thanks", "great", "awesome", "perfect", "good", "helpful", "appreciate", "love"]

        if any(w in t_lower for w in angry_words):
            sentiment = "ANGRY"
        elif any(w in t_lower for w in frustrated_words):
            sentiment = "FRUSTRATED"
        elif any(w in t_lower for w in positive_words):
            sentiment = "POSITIVE"

        return {
            "intent": intent,
            "sentiment": sentiment,
            "urgency": urgency,
            "is_escalated": is_escalated
        }

    @classmethod
    def summarize_conversation(cls, messages: list[dict]) -> str:
        """Generates a concise 1-2 sentence executive summary of a customer conversation."""
        if not messages:
            return "No messages exchanged in this session."
        
        customer_msgs = [m["content"] for m in messages if m.get("sender_type") in ("CUSTOMER", "customer")]
        if not customer_msgs:
            customer_msgs = [m.get("content", "") for m in messages]
        
        last_inquiry = customer_msgs[-1] if customer_msgs else "General support inquiry"
        first_inquiry = customer_msgs[0] if customer_msgs else last_inquiry
        
        if len(customer_msgs) == 1:
            return f"Customer initiated contact regarding: {first_inquiry[:140]}."
        return f"Customer inquired about '{first_inquiry[:80]}'. Final follow-up: '{last_inquiry[:80]}'."

    @classmethod
    def recommend_team_routing(cls, workspace, text: str):
        """Recommends the best team based on text/intent keywords."""
        t_lower = (text or "").lower()
        if any(w in t_lower for w in ["bill", "charge", "refund", "deduct", "invoice", "payment", "card", "price"]):
            team = Team.objects.filter(workspace=workspace, slug__in=["billing-support", "billing"]).first()
            if team:
                return team
        if any(w in t_lower for w in ["order", "ship", "deliver", "track", "package", "return", "defect", "exchange"]):
            team = Team.objects.filter(workspace=workspace, slug__in=["order-support", "orders", "shipping"]).first()
            if team:
                return team
        if any(w in t_lower for w in ["tech", "bug", "error", "broken", "login", "password", "crash", "api"]):
            team = Team.objects.filter(workspace=workspace, slug__in=["tech-support", "engineering", "technical"]).first()
            if team:
                return team
        return Team.objects.filter(workspace=workspace, is_active=True).first()

llm_service = LLMService()
