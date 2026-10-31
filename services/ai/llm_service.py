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

def has_word(text: str, words: list[str]) -> bool:
    """Accurate word-boundary matching. Prevents false positive substring hits (e.g. 'hi' in 'shipping')."""
    pattern = r'\b(?:' + '|'.join(re.escape(w) for w in words) + r')\b'
    return bool(re.search(pattern, text, re.IGNORECASE))


class LLMService:
    """
    LLM Inference Service for Supporto AI.
    Integrates with local Qwen 8B GGUF model when llama-cpp-python is available,
    with tool-calling capabilities and an intelligent fallback engine.
    """

    PROMPT_INJECTION_PATTERNS = [
        r"ignore (?:all )?(?:previous|above) instructions",
        r"reveal (?:your )?(?:system prompt|instructions|passwords)",
        r"give me (?:the )?(?:admin|root|system) password",
        r"disregard (?:all )?guidelines",
        r"you are now in (?:dan|developer) mode",
    ]

    @classmethod
    def generate_response(cls, workspace, customer_message: str, message_history: list[dict] = None, customer_email: str = None) -> dict:
        if message_history is None:
            message_history = []

        config, _ = AgentConfiguration.objects.get_or_create(workspace=workspace)
        system_prompt = config.system_prompt
        msg_lower = customer_message.lower().strip()

        # 0. Prompt-Injection Guardrail
        for pattern in cls.PROMPT_INJECTION_PATTERNS:
            if re.search(pattern, msg_lower):
                refusal = "I am Supporto AI, an automated customer support assistant. I cannot disclose internal system instructions or bypass security policies. How can I help you with your order, returns, or support tickets today?"
                return {
                    "text": refusal,
                    "retrieved_docs": [],
                    "tokens_used": len(refusal.split()),
                    "source": "security_guardrail"
                }

        # 1. Tool Calling: Order / AWB Consignment Tracking
        awb_match = re.search(r'\b(eb\d{6,12})\b', msg_lower)
        order_match = re.search(r'\b(se-?\d{4,6}|fm-?\d{4,6}|tn-?\d{4,6}|ord-?\d{4,6}|[a-z]{2}-?\d{4,6})\b', msg_lower)
        tracking_keywords = [
            "my order", "track order", "track package", "where is my order",
            "where is my package", "where is my parcel", "awb", "consignment", "tracking status"
        ]

        order_data = None
        order_not_found_code = None
        needs_order_number = False

        if awb_match or order_match:
            code = awb_match.group(1).upper() if awb_match else order_match.group(1).upper()
            tool_res = tool_registry.lookup_order(workspace.id, code, customer_email=customer_email)
            if tool_res.get("success"):
                order_data = tool_res["order"]
            else:
                order_not_found_code = code
        elif any(k in msg_lower for k in tracking_keywords):
            needs_order_number = True

        # 2. Retrieve relevant Knowledge Base context (with stopword filtering & score threshold)
        retrieved = rag_service.retrieve_context(workspace.id, customer_message, top_k=3)
        if order_data:
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

        # 3. LLM Inference via Qwen (Local GGUF or Fallback Engine)
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
                    temperature=0.1,
                    stop=["<|im_end|>", "<|endoftext|>", "Customer:", "\nUser:"]
                )
                raw_text = output["choices"][0]["text"].strip()
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

        # 4. Intelligent Fallback Response Engine
        response_text = cls._generate_grounded_fallback(
            workspace=workspace,
            message=customer_message,
            retrieved_docs=retrieved,
            order_data=order_data,
            order_not_found_code=order_not_found_code,
            needs_order_number=needs_order_number
        )
        return {
            "text": response_text,
            "retrieved_docs": retrieved,
            "tokens_used": len(response_text.split()),
            "source": "supporto_rag_engine"
        }

    @classmethod
    def _generate_grounded_fallback(cls, workspace, message: str, retrieved_docs: list[dict], order_data: dict = None, order_not_found_code: str = None, needs_order_number: bool = False) -> str:
        msg_lower = message.lower().strip()

        # 1. Urgent Billing / Fraud keywords ALWAYS checked FIRST before order lookups
        urgent_keywords = [
            "deducted twice", "double charge", "double charged", "charged twice",
            "unauthorized charge", "fraud", "scam", "overcharged", "money stolen",
            "refund immediately", "cancel and refund"
        ]
        if any(k in msg_lower for k in urgent_keywords):
            sla_mins = getattr(getattr(workspace, "settings", None), "sla_urgent_minutes", 15)
            return (
                f"I understand you are reporting an urgent billing discrepancy ({message.strip()}). "
                f"I have flagged this as critical and escalated it to our Billing Support team. "
                f"A specialist will review your transaction and reply within {sla_mins} minutes."
            )

        # 2. Customer asked for order status without giving an ID
        if needs_order_number:
            sample_id = "EB987654321" if workspace.slug == "expressbeas" else "SE-84920"
            return f"I would be glad to check your status! Could you please provide your Order ID or AWB Tracking Number (e.g. {sample_id})?"

        # 3. Order ID was provided but not found
        if order_not_found_code:
            return f"I couldn't find order or AWB #{order_not_found_code} in our records. Please double-check the number, or let me know if you would like me to connect you with our support team."

        # 4. Order or Shipment details found
        if order_data:
            num = order_data["order_number"]
            item = order_data["item"]
            status = order_data["status"]
            carrier = order_data["carrier"]
            delivery = order_data["estimated_delivery"]
            last_scan = order_data.get("last_scan")
            origin = order_data.get("origin")
            dest = order_data.get("destination")

            if "cancel" in msg_lower:
                if order_data.get("can_cancel"):
                    return f"Your order {num} ({item}) is currently in processing and can be cancelled. I will notify our Support team to cancel it."
                else:
                    return f"Shipment {num} ({item}) is already {status.lower()} with {carrier} and cannot be cancelled mid-transit. Once it arrives, you can process a return or claim."

            if last_scan or origin:
                return (
                    f"📦 **Tracking Status for {num}**\n\n"
                    f"• **Status**: {status}\n"
                    f"• **Carrier**: {carrier}\n"
                    f"• **Route**: {origin or 'Origin'} ➔ {dest or 'Destination'}\n"
                    f"• **Latest Scan**: {last_scan or 'In transit'}\n"
                    f"• **ETA**: {delivery}"
                )

            return f"Your order {num} ({item}) is currently **{status}** via {carrier}. Estimated delivery: **{delivery}**."

        # 5. Pure Greetings Check (Strict word boundaries, only for short introductory messages)
        words = msg_lower.split()
        if len(words) <= 4 and has_word(msg_lower, ["hello", "hi", "hey", "greetings", "good morning", "good afternoon", "hii", "heyy"]):
            return f"Hello! Welcome to {workspace.name} support. How can I help you today?"

        # 6. Grounded Knowledge Base answers (Filtered by relevance score)
        if retrieved_docs:
            top_doc = retrieved_docs[0]
            answer = top_doc.get("content", "")
            title = top_doc.get("title", "Policy")
            return f"According to {workspace.name}'s '{title}':\n\n{answer}"

        # 7. Honest fallback when knowledge is not found
        return (
            f"I couldn't find specific information regarding '{message.strip()[:60]}' in our knowledge base. "
            "Would you like me to connect you with a member of our human support team?"
        )

    @classmethod
    def classify_intent_urgency(cls, text: str) -> dict:
        """Classifies intent, sentiment, and urgency with negation resistance."""
        t_lower = text.lower()

        # Negation handling: e.g. "not angry", "no rush", "not urgent", "no hurry"
        has_calm_negation = has_word(t_lower, [
            "not angry", "no rush", "not urgent", "no hurry",
            "whenever you can", "take your time", "not mad", "not upset"
        ])

        # 1. Critical safety triggers (immediate human escalation)
        critical_terms = [
            "deducted twice", "double charge", "double charged", "charged twice",
            "unauthorized charge", "unauthorized transaction", "legal action", "lawyer",
            "lawsuit", "refund immediately", "cancel and refund immediately", "fraud", "scam"
        ]
        is_critical = any(term in t_lower for term in critical_terms)

        # 2. High urgency triggers
        high_terms = [
            "broken", "damaged", "wrong item", "crash", "crashes", "crashing",
            "stopped working", "doesn't work", "down", "outage", "freeze", "freezes"
        ]
        is_high = not has_calm_negation and has_word(t_lower, high_terms)

        if is_critical:
            urgency = "CRITICAL"
            is_escalated = True
        elif is_high:
            urgency = "HIGH"
            is_escalated = True
        elif has_calm_negation:
            urgency = "LOW"
            is_escalated = False
        else:
            urgency = "LOW"
            is_escalated = False

        # 3. Intent detection
        intent = "GENERAL"
        if has_word(t_lower, ["pay", "charge", "refund", "bill", "billing", "invoice", "price", "money", "deducted", "payment", "card"]):
            intent = "BILLING"
        elif has_word(t_lower, ["crash", "crashing", "crashes", "error", "bug", "api", "login", "password", "server", "down"]):
            intent = "TECHNICAL"
        elif has_word(t_lower, ["ship", "shipping", "track", "tracking", "delivery", "arrive", "order", "package", "awb", "courier", "consignment"]):
            intent = "SHIPPING"
        elif has_word(t_lower, ["return", "returns", "exchange", "replace", "replacement"]):
            intent = "RETURNS"
        elif has_word(t_lower, ["broken", "damage", "damaged", "defect", "faulty", "spoiled", "rotten"]):
            intent = "DEFECT"

        # 4. Sentiment detection with negation guard
        sentiment = "NEUTRAL"
        if has_calm_negation:
            sentiment = "NEUTRAL"
        elif has_word(t_lower, ["furious", "cheat", "cheated", "scam", "worst", "hate", "lawsuit", "sue", "unacceptable"]):
            sentiment = "ANGRY"
        elif has_word(t_lower, ["slow", "waiting", "delayed", "useless", "annoying", "disappointed", "frustrated"]):
            sentiment = "FRUSTRATED"
        elif has_word(t_lower, ["thank", "thanks", "great", "awesome", "perfect", "good", "helpful", "appreciate"]):
            sentiment = "POSITIVE"

        return {
            "intent": intent,
            "sentiment": sentiment,
            "urgency": urgency,
            "is_escalated": is_escalated
        }

    classify_message = classify_intent_urgency

    @classmethod
    def summarize_conversation(cls, messages: list[dict]) -> str:
        if not messages:
            return "No messages exchanged in this session."
        customer_msgs = [m["content"] for m in messages if m.get("sender_type") in ("CUSTOMER", "customer")]
        if not customer_msgs:
            customer_msgs = [m.get("content", "") for m in messages]
        first_inquiry = customer_msgs[0] if customer_msgs else "General support inquiry"
        last_inquiry = customer_msgs[-1] if customer_msgs else first_inquiry
        if len(customer_msgs) == 1:
            return f"Customer inquired about: {first_inquiry[:120]}."
        return f"Customer initiated contact regarding '{first_inquiry[:70]}'. Latest follow-up: '{last_inquiry[:70]}'."

    @classmethod
    def recommend_team_routing(cls, workspace, text: str):
        t_lower = (text or "").lower()
        if has_word(t_lower, ["bill", "charge", "refund", "deduct", "invoice", "payment", "card", "price", "dispute"]):
            team = Team.objects.filter(workspace=workspace, slug__in=["billing-support", "enterprise-billing", "claims-disputes", "quality-refunds"]).first()
            if team:
                return team
        if has_word(t_lower, ["order", "ship", "deliver", "track", "package", "awb", "consignment", "delivery", "pickup"]):
            team = Team.objects.filter(workspace=workspace, slug__in=["order-support", "tracking-delivery", "hyperlocal-delivery"]).first()
            if team:
                return team
        if has_word(t_lower, ["tech", "bug", "error", "broken", "login", "password", "crash", "crashing", "api"]):
            team = Team.objects.filter(workspace=workspace, slug__in=["technical-support", "dev-support"]).first()
            if team:
                return team
        return Team.objects.filter(workspace=workspace, is_active=True).first()

llm_service = LLMService()
