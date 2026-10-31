import re
import json
import logging
from apps.ai_engine.models import AgentConfiguration
from apps.teams.models import Team
from apps.orders.models import Order, Shipment
from apps.orders.utils import normalize_phone
from services.ai.model_manager import model_manager
from services.ai.rag_service import rag_service
from services.ai.prompt_builder import prompt_builder
from services.ai.tool_registry import tool_registry

logger = logging.getLogger(__name__)

def has_word(text: str, words: list[str]) -> bool:
    """Accurate word-boundary matching. Prevents false positive substring hits."""
    pattern = r'\b(?:' + '|'.join(re.escape(w) for w in words) + r')\b'
    return bool(re.search(pattern, text, re.IGNORECASE))


def extract_order_code(text: str) -> str | None:
    """
    Robust order and consignment AWB extractor.
    Handles awb123459876, 152785863851740, EB987654321, SE-84920, TN-88234, FM-44512,
    order #12345, parcel #12345, and numeric tracking codes up to 18 digits.
    """
    t = text.strip()
    # 1. Matches with awb prefix: e.g. awb123459876, awb 152785863851740, awb-123459876
    m = re.search(r'\bawb[:\s\-#]*([a-z0-9]{6,20})\b', t, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    # 2. Known prefixes: EB123456789, SE-84920, FM-8812, TN-201, ORD-12345, or XX-12345
    m = re.search(r'\b(eb\d{6,14}|se-?\d{4,8}|fm-?\d{4,8}|tn-?\d{4,8}|ord-?\d{4,8}|[a-z]{2}-?\d{4,8})\b', t, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    # 3. Phrases: order #12345, parcel #12345, package #12345, consignment #12345
    m = re.search(r'\b(?:order|parcel|package|consignment|shipment|tracking)[\s:#]+([a-z0-9\-]{5,20})\b', t, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    # 4. Long numeric sequences (8 to 18 digits) e.g. ExpressBeas consignments 152785863851740
    m = re.search(r'\b(\d{8,18})\b', t)
    if m:
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
    def generate_response(
        cls,
        workspace,
        customer_message: str,
        message_history: list[dict] = None,
        customer_email: str = None,
        customer_phone: str = None
    ) -> dict:
        if message_history is None:
            message_history = []

        config, _ = AgentConfiguration.objects.get_or_create(workspace=workspace)
        system_prompt = config.system_prompt
        msg_lower = customer_message.lower().strip()
        norm_phone = normalize_phone(customer_phone) if customer_phone else ""

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

        # 2. Extract Order / Consignment / AWB Code
        extracted_code = extract_order_code(customer_message)

        # 3. Intent: Order Cancellation
        if "cancel" in msg_lower and (extracted_code or any(w in msg_lower for w in ["order", "item", "purchase", "package"])):
            target_order = extracted_code
            if not target_order:
                # If no code in message, check customer's active orders
                if norm_phone:
                    cust_orders = tool_registry.list_customer_orders(workspace.id, phone=norm_phone)
                    cancellable = [o for o in cust_orders.get("orders", []) if o.get("is_cancellable")]
                    if len(cancellable) == 1:
                        target_order = cancellable[0]["order_number"]

            if target_order:
                if not norm_phone:
                    prompt_msg = "Please provide your registered 10-digit phone number to cancel an order."
                    return {"text": prompt_msg, "retrieved_docs": [], "tokens_used": len(prompt_msg.split()), "source": "auth_phone_required"}

                canc_res = tool_registry.cancel_order(workspace.id, order_number=target_order, phone=norm_phone, reason=customer_message)
                if not canc_res.get("success"):
                    return {"text": canc_res.get("error", "Could not cancel order."), "retrieved_docs": [], "tokens_used": 20, "source": "order_cancellation_failed"}

                ticket_num = canc_res["ticket_number"]
                team_name = canc_res.get("assigned_team", "Order Support")
                if canc_res.get("already_existed"):
                    reply = f"Order {target_order} cancellation was already registered under support ticket #{ticket_num}. Our {team_name} team is currently processing it."
                else:
                    reply = f"I have successfully cancelled order {target_order}. Your support ticket is #{ticket_num}. Our {team_name} team will process any necessary refund within 24-48 hours."

                return {"text": reply, "retrieved_docs": [], "tokens_used": len(reply.split()), "source": "order_cancellation_completed"}

        # 4. Intent: "What are my orders" / "Track my order" (without specific code)
        list_orders_queries = [
            "what are my orders", "my orders", "list my orders", "show my orders",
            "show orders", "view my orders", "where is my order", "where is my package",
            "track my order", "track my parcel", "where are my parcels", "my parcels", "my shipments"
        ]
        if not extracted_code and any(q in msg_lower for q in list_orders_queries):
            if not norm_phone:
                sample_id = "152785863851740" if workspace.slug == "expressbeas" else "SE-84920"
                prompt_msg = f"I'd be glad to look up your records! Please provide your registered 10-digit phone number or an Order / AWB Number (e.g. {sample_id})."
                return {"text": prompt_msg, "retrieved_docs": [], "tokens_used": len(prompt_msg.split()), "source": "phone_required_prompt"}

            orders_res = tool_registry.list_customer_orders(workspace.id, phone=norm_phone)
            reply = cls._format_orders_list(orders_res.get("orders", []), orders_res.get("shipments", []), workspace.name)
            return {"text": reply, "retrieved_docs": [], "tokens_used": len(reply.split()), "source": "db_customer_orders"}

        # 5. Intent: Return or Refund Status Inquiry
        if any(w in msg_lower for w in ["return status", "refund status", "my return", "my refund", "pickup status", "replacement status"]):
            if not norm_phone:
                return {"text": "Please provide your registered 10-digit phone number to check your return and refund status.", "retrieved_docs": [], "tokens_used": 15, "source": "phone_required_prompt"}
            ret_res = tool_registry.get_return_refund_status(workspace.id, query=extracted_code or "", phone=norm_phone)
            reply = cls._format_returns_list(ret_res.get("returns", []))
            return {"text": reply, "retrieved_docs": [], "tokens_used": len(reply.split()), "source": "db_return_status"}

        # 6. Intent: Support Tickets Status Inquiry
        if any(w in msg_lower for w in ["my ticket", "my tickets", "ticket status", "check my ticket", "open tickets"]):
            if not norm_phone:
                return {"text": "Please provide your registered 10-digit phone number to check your support tickets.", "retrieved_docs": [], "tokens_used": 15, "source": "phone_required_prompt"}
            tickets_res = tool_registry.get_customer_tickets(workspace.id, phone=norm_phone)
            reply = cls._format_tickets_list(tickets_res.get("tickets", []))
            return {"text": reply, "retrieved_docs": [], "tokens_used": len(reply.split()), "source": "db_customer_tickets"}

        # 7. Specific Order / Consignment Inquiry with Code
        if extracted_code:
            # Check if Order exists in DB
            order_exists = Order.objects.filter(workspace_id=workspace.id, order_number__iexact=extracted_code).exists()
            shipment_exists = Shipment.objects.filter(workspace_id=workspace.id, awb__iexact=extracted_code).exists()

            if order_exists:
                res = tool_registry.get_order_details(workspace.id, order_number=extracted_code, phone=norm_phone)
                if res.get("needs_phone"):
                    return {"text": f"Please provide your registered 10-digit phone number to check details for order {extracted_code}.", "retrieved_docs": [], "tokens_used": 20, "source": "phone_required"}
                if not res.get("verified"):
                    return {"text": res.get("error", "I couldn't verify that order against your phone number."), "retrieved_docs": [], "tokens_used": 15, "source": "phone_verification_denied"}

                reply = cls._format_order_details(res["order"])
                return {"text": reply, "retrieved_docs": [], "tokens_used": len(reply.split()), "source": "db_order_details"}

            elif shipment_exists:
                res = tool_registry.get_shipment_tracking(workspace.id, awb=extracted_code, phone=norm_phone)
                if res.get("needs_phone"):
                    return {"text": f"Please provide your registered 10-digit phone number to track consignment {extracted_code}.", "retrieved_docs": [], "tokens_used": 20, "source": "phone_required"}
                if not res.get("verified"):
                    return {"text": res.get("error", "I couldn't verify that order against your phone number."), "retrieved_docs": [], "tokens_used": 15, "source": "phone_verification_denied"}

                reply = cls._format_shipment_details(res["shipment"])
                return {"text": reply, "retrieved_docs": [], "tokens_used": len(reply.split()), "source": "db_shipment_tracking"}

            else:
                # Check external webhook fallback
                wh_res = tool_registry.lookup_order(workspace.id, extracted_code, customer_phone=norm_phone, customer_email=customer_email)
                if wh_res.get("success"):
                    reply = cls._format_order_reply(workspace, wh_res["order"], msg_lower)
                    return {"text": reply, "retrieved_docs": [], "tokens_used": len(reply.split()), "source": "external_webhook"}

                not_found_msg = (
                    f"I could not find order or AWB #{extracted_code} in our {workspace.name} records. "
                    "The order was not found. Please double-check the tracking number, or let me know if you would like me to connect you with our support team."
                )
                return {
                    "text": not_found_msg,
                    "retrieved_docs": [],
                    "tokens_used": len(not_found_msg.split()),
                    "source": "order_not_found"
                }

        # 8. Pure Greetings Check (Strict word boundaries, only for short introductory messages)
        words = msg_lower.split()
        if len(words) <= 4 and has_word(msg_lower, ["hello", "hi", "hey", "greetings", "good morning", "good afternoon", "hii", "heyy"]):
            greeting_msg = f"Hello! Welcome to {workspace.name} support. How can I help you today?"
            return {
                "text": greeting_msg,
                "retrieved_docs": [],
                "tokens_used": len(greeting_msg.split()),
                "source": "greeting_handler"
            }

        # 9. Closings & Gratitude
        if has_word(msg_lower, ["thanks", "thank you", "bye", "goodbye", "have a nice day", "have a good day", "thanks bye"]):
            closing_msg = "You're very welcome! Feel free to reach out anytime if you need help with your orders or services. Have a wonderful day!"
            return {
                "text": closing_msg,
                "retrieved_docs": [],
                "tokens_used": len(closing_msg.split()),
                "source": "closing_handler"
            }

        # 10. Retrieve relevant Knowledge Base context
        retrieved = rag_service.retrieve_context(workspace.id, customer_message, top_k=3)

        # 11. LLM Inference via Qwen (Local GGUF if available)
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

        # 12. Grounded Knowledge Base answers (Filtered by relevance score)
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

    # -------------------------------------------------------------------------
    # Comprehensive Deterministic Grounded Formatters
    # -------------------------------------------------------------------------

    @classmethod
    def _format_order_details(cls, order_data: dict) -> str:
        num = order_data["order_number"]
        status = order_data["status"]
        payment = order_data["payment"]
        pricing = order_data["pricing"]
        items = order_data["items"]
        carrier = order_data.get("carrier") or "Standard Shipping"
        eta = order_data.get("estimated_delivery")
        delivered = order_data.get("delivered_at")
        cancelled = order_data.get("cancelled_at")
        returns = order_data.get("return_requests", [])
        ticket = order_data.get("linked_ticket")

        lines = [f"📦 **Order Details: #{num}**\n"]
        lines.append(f"• **Status**: **{status}**")
        if delivered:
            lines.append(f"• **Delivered At**: {delivered}")
        elif cancelled:
            lines.append(f"• **Cancelled At**: {cancelled}")
        elif eta:
            lines.append(f"• **Estimated Delivery**: {eta} (Carrier: {carrier})")

        lines.append(f"• **Payment**: {payment['method']} ({payment['status']})")
        lines.append(f"• **Pricing**: Total: **{pricing['total']}** (Subtotal: {pricing['subtotal']}, Shipping: {pricing['shipping_fee']}, Discount: {pricing['discount']})")

        if items:
            lines.append("\n**Items:**")
            for it in items:
                lines.append(f"  - {it['name']} (Qty: {it['quantity']}) — {it['line_total']}")

        if returns:
            lines.append("\n**Return / Refund Status:**")
            for r in returns:
                exp = f" | Expected: {r['expected_refund_by']}" if r.get("expected_refund_by") else ""
                lines.append(f"  - {r['type']}: **{r['status']}** | Refund: {r['refund_amount']} ({r['refund_status']}){exp}")

        if ticket:
            lines.append(f"\n• **Linked Support Ticket**: #{ticket}")

        return "\n".join(lines)

    @classmethod
    def _format_shipment_details(cls, shipment_data: dict) -> str:
        awb = shipment_data["awb"]
        status = shipment_data["status"]
        origin = shipment_data["origin_city"]
        dest = shipment_data["destination_city"]
        service = shipment_data["service_type"]
        weight = shipment_data["weight_kg"]
        eta = shipment_data.get("estimated_delivery")
        delivered = shipment_data.get("delivered_at")
        timeline = shipment_data.get("timeline", [])

        lines = [f"🚚 **Consignment Tracking: #{awb}**\n"]
        lines.append(f"• **Status**: **{status}**")
        lines.append(f"• **Route**: {origin} ➔ {dest} ({service}, {weight} kg)")
        if delivered:
            lines.append(f"• **Delivered**: {delivered}")
        elif eta:
            lines.append(f"• **Estimated Delivery**: {eta}")

        if timeline:
            lines.append("\n**Tracking Timeline:**")
            for ev in timeline:
                rem = f" — {ev['remarks']}" if ev.get("remarks") else ""
                lines.append(f"  • `{ev['occurred_at']}` | **{ev['status']}** ({ev['location']}){rem}")

        return "\n".join(lines)

    @classmethod
    def _format_orders_list(cls, orders: list, shipments: list, company_name: str) -> str:
        if not orders and not shipments:
            return f"No active or past records were found under your registered phone number at {company_name}."

        lines = [f"Here are the records found under your phone number at {company_name}:\n"]
        if orders:
            lines.append("**Orders:**")
            for o in orders:
                lines.append(f"• **#{o['order_number']}** — {o['items_summary']} | Total: {o['total']} | Status: **{o['status']}**")
        if shipments:
            lines.append("\n**Consignments:**")
            for s in shipments:
                lines.append(f"• **AWB {s['awb']}** — {s['origin']} ➔ {s['destination']} ({s['service_type']}) | Status: **{s['status']}**")

        lines.append("\nTo view full details or manage any order, simply mention its order or AWB number!")
        return "\n".join(lines)

    @classmethod
    def _format_returns_list(cls, returns: list) -> str:
        if not returns:
            return "You have no active return or refund requests under this phone number."
        lines = ["**Return & Refund Status:**\n"]
        for r in returns:
            t_note = f" (Ticket #{r['linked_ticket']})" if r.get("linked_ticket") else ""
            lines.append(f"• **Order #{r['order_number']}** — {r['type']}: **{r['status']}** | Refund: {r['refund_amount']} ({r['refund_status']}){t_note}")
        return "\n".join(lines)

    @classmethod
    def _format_tickets_list(cls, tickets: list) -> str:
        if not tickets:
            return "You currently have no support tickets registered under this phone number."
        lines = ["**Your Support Tickets:**\n"]
        for t in tickets:
            lines.append(f"• **#{t['ticket_number']}** — {t['subject']} | Status: **{t['status']}** (Priority: {t['priority']}, Team: {t['assigned_team']})")
        return "\n".join(lines)

    @staticmethod
    def _format_order_reply(workspace, order_data: dict, msg_lower: str) -> str:
        num = order_data["order_number"]
        item = order_data.get("item", "Store Item")
        status = order_data["status"]
        carrier = order_data.get("carrier", "Standard Courier")
        delivery = order_data.get("estimated_delivery", "Pending")
        last_scan = order_data.get("last_scan")
        origin = order_data.get("origin")
        dest = order_data.get("destination")

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

        # Negation handling
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
