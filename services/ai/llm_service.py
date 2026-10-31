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


def extract_order_code(text: str) -> str | None:
    """
    Robust order and consignment AWB extractor.
    Handles awb123459876, awb 123456789, EB987654321, SE-84920, TN-88234, FM-44512,
    order #12345, parcel #12345, and numeric tracking codes in tracking contexts.
    """
    t = text.strip()
    # 1. Matches with awb prefix: e.g. awb123459876, awb 123459876, awb-123459876
    m = re.search(r'\bawb[:\s\-#]*([a-z0-9]{6,16})\b', t, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    # 2. Known prefixes: EB123456789, SE-84920, FM-8812, TN-201, ORD-12345, or XX-12345
    m = re.search(r'\b(eb\d{6,14}|se-?\d{4,8}|fm-?\d{4,8}|tn-?\d{4,8}|ord-?\d{4,8}|[a-z]{2}-?\d{4,8})\b', t, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    # 3. Phrases: order #12345, parcel #12345, package #12345, consignment #12345
    m = re.search(r'\b(?:order|parcel|package|consignment|shipment|tracking)[\s:#]+([a-z0-9\-]{5,16})\b', t, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    # 4. Long numeric sequences (8 to 14 digits) in tracking queries
    m = re.search(r'\b(\d{8,14})\b', t)
    if m and any(k in t.lower() for k in ["track", "parcel", "package", "shipment", "awb", "order", "where", "find"]):
        return m.group(1)
    return None


class LLMService:
    """
    LLM Inference Service for Supporto AI.
    Features deterministic pre-LLM guards, audited tool execution, and grounded fallback engine.
    """

    PROMPT_INJECTION_PATTERNS = [
        r"ignore (?:all )?(?:previous|above) instructions",
        r"reveal (?:your )?(?:system prompt|instructions|passwords)",
        r"give me (?:the )?(?:admin|root|system) password",
        r"disregard (?:all )?guidelines",
        r"disregard (?:all )?prior rules",
        r"print (?:your )?(?:system prompt|internal prompt)",
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

        # 1. Urgent Billing / Fraud Check (Pre-LLM Guard)
        urgent_keywords = [
            "deducted twice", "double charge", "double charged", "charged twice",
            "unauthorized charge", "fraud", "scam", "overcharged", "money stolen",
            "refund immediately", "cancel and refund"
        ]
        if any(k in msg_lower for k in urgent_keywords):
            sla_mins = getattr(getattr(workspace, "settings", None), "sla_urgent_minutes", 15)
            escalation_text = (
                f"I understand you are reporting an urgent billing discrepancy ({customer_message.strip()}). "
                f"I have flagged this as critical and escalated it to our Billing Support team. "
                f"A specialist will review your transaction and reply within {sla_mins} minutes."
            )
            return {
                "text": escalation_text,
                "retrieved_docs": [],
                "tokens_used": len(escalation_text.split()),
                "source": "urgent_billing_guard"
            }

        # 2. Extract Order / AWB Consignment Code
        extracted_code = extract_order_code(customer_message)
        tracking_keywords = [
            "my order", "track order", "track package", "where is my order",
            "where is my package", "where is my parcel", "find my parcel", "awb", "consignment", "tracking status"
        ]

        order_data = None
        order_not_found_code = None
        needs_order_number = False

        if extracted_code:
            tool_res = tool_registry.lookup_order(workspace.id, extracted_code, customer_email=customer_email)
            if not tool_res.get("success") and workspace.slug == "expressbeas" and not extracted_code.startswith("EB"):
                # Try prefixing EB for ExpressBeas consignments
                tool_res = tool_registry.lookup_order(workspace.id, f"EB{extracted_code}", customer_email=customer_email)

            if tool_res.get("success"):
                order_data = tool_res["order"]
            else:
                order_not_found_code = extracted_code
        elif any(k in msg_lower for k in tracking_keywords):
            needs_order_number = True

        # 3. Deterministic Pre-LLM Interceptions (Zero Hallucination Guarantee)
        if order_not_found_code:
            not_found_msg = (
                f"I could not find order or AWB #{order_not_found_code} in our {workspace.name} records. "
                "The order was not found. Please double-check the tracking number, or let me know if you would like me to connect you with our support team."
            )
            return {
                "text": not_found_msg,
                "retrieved_docs": [],
                "tokens_used": len(not_found_msg.split()),
                "source": "deterministic_order_lookup"
            }

        if needs_order_number:
            sample_id = "EB987654321" if workspace.slug == "expressbeas" else "SE-84920"
            prompt_msg = f"I would be glad to check your status! Could you please provide your Order ID or AWB Tracking Number (e.g. {sample_id})?"
            return {
                "text": prompt_msg,
                "retrieved_docs": [],
                "tokens_used": len(prompt_msg.split()),
                "source": "deterministic_order_prompt"
            }

        if order_data:
            details_msg = cls._format_order_reply(workspace, order_data, msg_lower)
            return {
                "text": details_msg,
                "retrieved_docs": [],
                "tokens_used": len(details_msg.split()),
                "source": "deterministic_order_details"
            }

        # 4. Pure Greetings Check (Strict word boundaries, only for short introductory messages)
        words = msg_lower.split()
        if len(words) <= 4 and has_word(msg_lower, ["hello", "hi", "hey", "greetings", "good morning", "good afternoon", "hii", "heyy"]):
            greeting_msg = f"Hello! Welcome to {workspace.name} support. How can I help you today?"
            return {
                "text": greeting_msg,
                "retrieved_docs": [],
                "tokens_used": len(greeting_msg.split()),
                "source": "greeting_handler"
            }

        # 5. Closings & Gratitude
        if has_word(msg_lower, ["thanks", "thank you", "bye", "goodbye", "have a nice day", "have a good day", "thanks bye"]):
            closing_msg = "You're very welcome! Feel free to reach out anytime if you need help with your orders or services. Have a wonderful day!"
            return {
                "text": closing_msg,
                "retrieved_docs": [],
                "tokens_used": len(closing_msg.split()),
                "source": "closing_handler"
            }

        # 6. Retrieve relevant Knowledge Base context
        retrieved = rag_service.retrieve_context(workspace.id, customer_message, top_k=3)

        # 7. LLM Inference via Qwen (Local GGUF or Grounded Fallback Engine)
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

        # 8. Grounded Knowledge Base answers (Filtered by relevance score)
        if retrieved:
            top_doc = retrieved[0]
            answer = top_doc.get("content", "")
            title = top_doc.get("title", "Policy")
            response_text = f"According to {workspace.name}'s '{title}':\n\n{answer}"
        else:
            response_text = (
                f"I couldn't find specific information regarding '{customer_message.strip()[:60]}' in our knowledge base. "
                "Would you like me to connect you with a member of our human support team?"
            )

        return {
            "text": response_text,
            "retrieved_docs": retrieved,
            "tokens_used": len(response_text.split()),
            "source": "supporto_rag_engine"
        }

    @staticmethod
    def _format_order_reply(workspace, order_data: dict, msg_lower: str) -> str:
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
                return f"Your order {num} ({item}) is currently in processing and eligible for cancellation. I will submit a formal cancellation request to our Order Support team."
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

    @classmethod
    def classify_intent_urgency(cls, text: str) -> dict:
        """Classifies intent, sentiment, and urgency with negation resistance and human handoff detection."""
        t_lower = text.lower()

        # Negation handling: e.g. "not angry", "no rush", "not urgent", "no hurry"
        has_calm_negation = has_word(t_lower, [
            "not angry", "no rush", "not urgent", "no hurry",
            "whenever you can", "take your time", "not mad", "not upset"
        ])

        # 0. Human handoff request detection
        is_human_handoff = has_word(t_lower, [
            "human", "agent", "real person", "representative", "support person",
            "talk to someone", "customer care executive", "connect to agent",
            "connect to human", "speak with someone", "live person", "real human"
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
        elif is_human_handoff or is_high:
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
        if is_human_handoff:
            intent = "HUMAN_HANDOFF"
        elif has_word(t_lower, ["pay", "charge", "refund", "bill", "billing", "invoice", "price", "money", "deducted", "payment", "card"]):
            intent = "BILLING"
        elif has_word(t_lower, ["crash", "crashing", "crashes", "error", "bug", "api", "login", "password", "server", "down", "freeze"]):
            intent = "TECHNICAL"
        elif has_word(t_lower, ["ship", "shipping", "track", "tracking", "delivery", "arrive", "order", "package", "awb", "courier", "consignment", "parcel"]):
            intent = "SHIPPING"
        elif has_word(t_lower, ["cancel", "cancellation"]):
            intent = "RETURNS"
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
        if has_word(t_lower, ["tech", "bug", "error", "broken", "login", "password", "crash", "crashing", "api", "freeze"]):
            team = Team.objects.filter(workspace=workspace, slug__in=["technical-support", "dev-support"]).first()
            if team:
                return team
        if has_word(t_lower, ["order", "ship", "deliver", "track", "package", "awb", "consignment", "delivery", "pickup", "parcel"]):
            team = Team.objects.filter(workspace=workspace, slug__in=["tracking-delivery", "order-support", "claims-disputes", "hyperlocal-delivery"]).first()
            if team:
                return team
        return Team.objects.filter(workspace=workspace, is_active=True).first()

llm_service = LLMService()
