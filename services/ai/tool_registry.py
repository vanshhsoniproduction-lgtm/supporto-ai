import logging
import re
import hmac
import hashlib
import time
import urllib.request
import urllib.parse
import json
from django.conf import settings
from django.utils import timezone
from django.db.models import Q
from apps.workspaces.models import Workspace, WorkspaceWebhook, WorkspaceSettings
from apps.knowledge_base.models import KnowledgeDocument
from apps.tickets.models import Ticket, TicketAssignment, TicketEvent
from apps.teams.models import Team
from apps.customers.models import Customer
from apps.conversations.models import Conversation
from apps.ai_engine.models import ToolExecution, AgentRun
from apps.orders.models import Order, OrderItem, Shipment, ShipmentEvent, ReturnRequest
from apps.orders.utils import normalize_phone
from services.ai.rag_service import rag_service

logger = logging.getLogger(__name__)

PRIVATE_IP_PREFIXES = ("127.", "10.", "192.168.", "169.254.", "0.0.0.0")

def is_safe_url(url: str) -> bool:
    """SSRF protection: rejects non-http(s), and in production rejects localhost and private RFC-1918 IPs."""
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = (parsed.hostname or "").lower()
        if getattr(settings, "DEBUG", False) and host in ("localhost", "127.0.0.1", "testserver"):
            return True
        if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return False
        if any(host.startswith(p) for p in PRIVATE_IP_PREFIXES):
            return False
        if host.startswith("172."):
            parts = host.split(".")
            if len(parts) >= 2 and parts[1].isdigit() and 16 <= int(parts[1]) <= 31:
                return False
        return True
    except Exception:
        return False


class ToolRegistry:
    """
    Registry of controlled AI tools. Every tool is strictly workspace-scoped
    and audited. Never exposes raw SQL or unrestricted file system access.
    """

    @classmethod
    def get_tools_schema(cls) -> list[dict]:
        """Returns standard JSON schemas for LLM function/tool calling."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "list_customer_orders",
                    "description": "List all active and past orders or courier consignments belonging to the verified customer.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "phone": {
                                "type": "string",
                                "description": "Customer's registered 10-digit phone number."
                            }
                        },
                        "required": ["phone"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_order_details",
                    "description": "Retrieve comprehensive details for a specific e-commerce order (items, pricing, tracking, delivery date, return window). Requires phone verification.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "order_number": {
                                "type": "string",
                                "description": "The exact order number (e.g. SE-84920)."
                            },
                            "phone": {
                                "type": "string",
                                "description": "Customer's registered 10-digit phone number for identity verification."
                            }
                        },
                        "required": ["order_number", "phone"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_shipment_tracking",
                    "description": "Track a courier shipment / AWB consignment, returning real-time status and complete timeline events. Requires phone verification.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "awb": {
                                "type": "string",
                                "description": "The consignment AWB tracking number (e.g. 152785863851740)."
                            },
                            "phone": {
                                "type": "string",
                                "description": "Customer's registered 10-digit phone number for identity verification."
                            }
                        },
                        "required": ["awb", "phone"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_customer_tickets",
                    "description": "List existing support tickets raised by or associated with this customer phone number.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "phone": {
                                "type": "string",
                                "description": "Customer's registered 10-digit phone number."
                            }
                        },
                        "required": ["phone"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_return_refund_status",
                    "description": "Check the status of return and refund requests for an order or customer.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "phone": {
                                "type": "string",
                                "description": "Customer's registered 10-digit phone number."
                            },
                            "order_number": {
                                "type": "string",
                                "description": "Optional order number to check returns for."
                            }
                        },
                        "required": ["phone"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "cancel_order",
                    "description": "Cancel an eligible order and automatically generate or reference a human support ticket.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "order_number": {
                                "type": "string",
                                "description": "Order number to cancel (e.g. SE-84922)."
                            },
                            "phone": {
                                "type": "string",
                                "description": "Customer's registered 10-digit phone number."
                            },
                            "reason": {
                                "type": "string",
                                "description": "Reason for cancellation."
                            }
                        },
                        "required": ["order_number", "phone"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "lookup_order",
                    "description": "Look up real-time status of an order or courier AWB consignment number.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "order_number": {
                                "type": "string",
                                "description": "The exact order number (e.g. SE-84920) or courier AWB number (e.g. 152785863851740)."
                            }
                        },
                        "required": ["order_number"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_knowledge_base",
                    "description": "Search the company support knowledge base for returns, shipping, policies, and FAQs.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search terms or question."
                            }
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_ticket_status",
                    "description": "Check the status of an existing support ticket by ticket number.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ticket_number": {
                                "type": "string",
                                "description": "The ticket number (e.g. TK-260101)."
                            }
                        },
                        "required": ["ticket_number"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "escalate_to_human",
                    "description": "Escalate urgent customer issues (double charges, fraud, severe defect) to human support team.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "reason": {
                                "type": "string",
                                "description": "Specific reason for human escalation."
                            }
                        },
                        "required": ["reason"]
                    }
                }
            }
        ]

    @classmethod
    def execute_tool(cls, workspace_id: int, tool_name: str, arguments: dict, customer_id: int = None, conversation_id: int = None, agent_run: AgentRun = None) -> dict:
        """Executes a declared tool in a strictly audited sandbox, logging to ToolExecution."""
        result = {"success": False, "error": f"Unknown tool '{tool_name}'"}

        try:
            phone = arguments.get("phone", "")
            if not phone and conversation_id:
                conv = Conversation.objects.filter(id=conversation_id, workspace_id=workspace_id).first()
                if conv:
                    phone = (conv.customer.normalized_phone if conv.customer else None) or (conv.customer.phone if conv.customer else None) or ""

            if tool_name == "list_customer_orders":
                result = cls.list_customer_orders(workspace_id=workspace_id, phone=phone)
            elif tool_name == "get_order_details":
                order_num = arguments.get("order_number", "")
                result = cls.get_order_details(workspace_id=workspace_id, order_number=order_num, phone=phone)
            elif tool_name == "get_shipment_tracking":
                awb = arguments.get("awb", "")
                result = cls.get_shipment_tracking(workspace_id=workspace_id, awb=awb, phone=phone)
            elif tool_name == "get_customer_tickets":
                result = cls.get_customer_tickets(workspace_id=workspace_id, phone=phone)
            elif tool_name == "get_return_refund_status":
                order_num = arguments.get("order_number", "")
                result = cls.get_return_refund_status(workspace_id=workspace_id, query=order_num, phone=phone)
            elif tool_name == "cancel_order":
                order_num = arguments.get("order_number", "")
                reason = arguments.get("reason", "")
                result = cls.cancel_order(workspace_id=workspace_id, order_number=order_num, phone=phone, reason=reason)
            elif tool_name == "lookup_order":
                order_num = arguments.get("order_number", "")
                result = cls.lookup_order(workspace_id=workspace_id, order_number=order_num, customer_phone=phone)
            elif tool_name == "search_knowledge_base":
                query = arguments.get("query", "")
                result = cls.search_knowledge_base(workspace_id=workspace_id, query=query)
            elif tool_name == "get_ticket_status":
                ticket_num = arguments.get("ticket_number", "")
                result = cls.get_ticket_status(workspace_id=workspace_id, ticket_number=ticket_num)
            elif tool_name == "escalate_to_human":
                reason = arguments.get("reason", "Customer escalation request")
                if conversation_id:
                    result = cls.escalate_to_human(workspace_id=workspace_id, conversation_id=conversation_id, reason=reason)
                else:
                    result = {"success": False, "error": "No active conversation to escalate"}
            elif tool_name == "create_ticket":
                if customer_id:
                    result = cls.create_ticket(
                        workspace_id=workspace_id,
                        customer_id=customer_id,
                        subject=arguments.get("subject", "Support Inquiry"),
                        description=arguments.get("description", ""),
                        priority=arguments.get("priority", "MEDIUM"),
                        category=arguments.get("category", "General Support")
                    )
                else:
                    result = {"success": False, "error": "Customer ID required to create ticket"}
        except Exception as e:
            logger.error(f"Error executing tool '{tool_name}': {e}")
            result = {"success": False, "error": str(e)}

        # Audit log in ToolExecution
        if agent_run:
            try:
                ToolExecution.objects.create(
                    agent_run=agent_run,
                    tool_name=tool_name,
                    arguments=arguments,
                    result=result,
                    is_success=result.get("success", False)
                )
            except Exception as e:
                logger.warning(f"Could not log ToolExecution: {e}")

        return result

    # -------------------------------------------------------------------------
    # Real SQL Data Layer Tools (Workspace-Scoped & Phone-Verified)
    # -------------------------------------------------------------------------

    @classmethod
    def list_customer_orders(cls, workspace_id: int, phone: str) -> dict:
        """Returns all orders and shipments for the caller's phone number in this workspace."""
        if not phone or not phone.strip():
            return {
                "success": False,
                "needs_phone": True,
                "error": "Please provide your registered 10-digit phone number to check your orders."
            }

        norm_phone = normalize_phone(phone)
        if len(norm_phone) != 10:
            return {
                "success": False,
                "error": "Invalid phone number. Please enter a valid 10-digit mobile number."
            }

        orders_qs = Order.objects.filter(workspace_id=workspace_id, customer_phone=norm_phone).prefetch_related("items").order_by("-placed_at")
        shipments_qs = Shipment.objects.filter(
            workspace_id=workspace_id
        ).filter(
            Q(receiver_phone=norm_phone) | Q(sender_phone=norm_phone)
        ).order_by("-created_at")

        orders_data = []
        for o in orders_qs:
            items_summary = ", ".join([f"{item.name} (x{item.quantity})" for item in o.items.all()]) or "Order item"
            orders_data.append({
                "order_number": o.order_number,
                "status": o.status,
                "items_summary": items_summary,
                "total": f"₹{o.total:,.2f}",
                "currency": o.currency,
                "payment_status": o.payment_status,
                "placed_at": o.placed_at.strftime("%Y-%m-%d %H:%M"),
                "estimated_delivery": o.estimated_delivery.strftime("%Y-%m-%d") if o.estimated_delivery else None,
                "carrier": o.carrier,
                "is_cancellable": o.is_cancellable,
                "is_return_eligible": o.is_return_eligible
            })

        shipments_data = []
        for s in shipments_qs:
            shipments_data.append({
                "awb": s.awb,
                "service_type": s.service_type,
                "status": s.status,
                "origin": s.origin_city,
                "destination": s.destination_city,
                "current_location": s.current_location,
                "estimated_delivery": s.estimated_delivery.strftime("%Y-%m-%d") if s.estimated_delivery else None,
                "created_at": s.created_at.strftime("%Y-%m-%d %H:%M")
            })

        total_count = len(orders_data) + len(shipments_data)
        return {
            "success": True,
            "count": total_count,
            "orders": orders_data,
            "shipments": shipments_data,
            "phone": norm_phone
        }

    @classmethod
    def get_order_details(cls, workspace_id: int, order_number: str, phone: str = None) -> dict:
        """
        Retrieves full order details from real SQL records.
        Strict verification: Reveals details ONLY if caller phone matches order's customer_phone.
        """
        if not order_number or not order_number.strip():
            return {"success": False, "error": "No order number provided."}

        order_num = order_number.strip().upper()
        order = Order.objects.filter(workspace_id=workspace_id, order_number__iexact=order_num).prefetch_related("items", "return_requests").first()

        if not order:
            # Check external user-configured webhook if active
            wh_res = cls._try_external_webhook(workspace_id=workspace_id, code=order_num)
            if wh_res.get("success"):
                return wh_res
            return {
                "success": False,
                "error": f"Order '{order_num}' was not found in our records."
            }

        # Verification check
        if not phone or not phone.strip():
            return {
                "success": False,
                "needs_phone": True,
                "order_number": order_num,
                "error": "Please provide your registered 10-digit phone number to check this order."
            }

        norm_phone = normalize_phone(phone)
        if norm_phone != order.customer_phone:
            # Leak NOTHING
            return {
                "success": False,
                "verified": False,
                "error": "I couldn't verify that order against your phone number."
            }

        items_list = [
            {
                "name": it.name,
                "sku": it.sku,
                "quantity": it.quantity,
                "unit_price": f"₹{it.unit_price:,.2f}",
                "line_total": f"₹{it.line_total:,.2f}"
            }
            for it in order.items.all()
        ]

        returns_list = [
            {
                "type": r.type,
                "status": r.status,
                "reason": r.reason,
                "refund_amount": f"₹{r.refund_amount:,.2f}",
                "refund_status": r.refund_status,
                "expected_refund_by": r.expected_refund_by.strftime("%Y-%m-%d") if r.expected_refund_by else None
            }
            for r in order.return_requests.all()
        ]

        # Check for any linked tickets
        linked_ticket = Ticket.objects.filter(workspace_id=workspace_id, related_order=order).order_by("-created_at").first()

        order_data = {
            "order_number": order.order_number,
            "customer_name": order.customer_name,
            "status": order.status,
            "items": items_list,
            "pricing": {
                "subtotal": f"₹{order.subtotal:,.2f}",
                "shipping_fee": f"₹{order.shipping_fee:,.2f}",
                "discount": f"₹{order.discount:,.2f}",
                "total": f"₹{order.total:,.2f}",
                "currency": order.currency
            },
            "payment": {
                "method": order.payment_method,
                "status": order.payment_status
            },
            "placed_at": order.placed_at.strftime("%Y-%m-%d %H:%M"),
            "estimated_delivery": order.estimated_delivery.strftime("%Y-%m-%d") if order.estimated_delivery else None,
            "delivered_at": order.delivered_at.strftime("%Y-%m-%d %H:%M") if order.delivered_at else None,
            "cancelled_at": order.cancelled_at.strftime("%Y-%m-%d %H:%M") if order.cancelled_at else None,
            "carrier": order.carrier,
            "shipping_address": f"{order.shipping_address}, {order.city} - {order.pincode}".strip(", -"),
            "is_cancellable": order.is_cancellable,
            "is_return_eligible": order.is_return_eligible,
            "return_eligible_until": order.return_eligible_until.strftime("%Y-%m-%d") if order.return_eligible_until else None,
            "return_requests": returns_list,
            "linked_ticket": linked_ticket.ticket_number if linked_ticket else None,
            "notes": order.notes
        }

        return {
            "success": True,
            "verified": True,
            "order": order_data
        }

    @classmethod
    def get_shipment_tracking(cls, workspace_id: int, awb: str, phone: str = None) -> dict:
        """
        Retrieves real-time courier shipment tracking with full event timeline.
        Strict verification: Caller phone must match sender_phone or receiver_phone.
        """
        if not awb or not awb.strip():
            return {"success": False, "error": "No AWB consignment number provided."}

        awb_clean = awb.strip().upper()
        shipment = Shipment.objects.filter(workspace_id=workspace_id, awb__iexact=awb_clean).prefetch_related("events").first()

        if not shipment:
            wh_res = cls._try_external_webhook(workspace_id=workspace_id, code=awb_clean)
            if wh_res.get("success"):
                return wh_res
            return {
                "success": False,
                "error": f"Consignment AWB '{awb_clean}' was not found in our dispatch records."
            }

        if not phone or not phone.strip():
            return {
                "success": False,
                "needs_phone": True,
                "awb": awb_clean,
                "error": "Please provide your registered 10-digit phone number to check this shipment."
            }

        norm_phone = normalize_phone(phone)
        if norm_phone not in (shipment.receiver_phone, shipment.sender_phone):
            return {
                "success": False,
                "verified": False,
                "error": "I couldn't verify that order against your phone number."
            }

        events_data = [
            {
                "status": ev.status,
                "location": ev.location,
                "occurred_at": ev.occurred_at.strftime("%d %b %Y, %I:%M %p"),
                "remarks": ev.remarks
            }
            for ev in shipment.events.all()
        ]

        shipment_data = {
            "awb": shipment.awb,
            "service_type": shipment.service_type,
            "weight_kg": float(shipment.weight_kg),
            "status": shipment.status,
            "origin_city": shipment.origin_city,
            "destination_city": shipment.destination_city,
            "current_location": shipment.current_location,
            "sender_name": shipment.sender_name,
            "receiver_name": shipment.receiver_name,
            "estimated_delivery": shipment.estimated_delivery.strftime("%d %b %Y") if shipment.estimated_delivery else None,
            "delivered_at": shipment.delivered_at.strftime("%d %b %Y, %I:%M %p") if shipment.delivered_at else None,
            "cod_amount": float(shipment.cod_amount) if shipment.cod_amount else None,
            "timeline": events_data,
            "latest_event": events_data[-1] if events_data else None
        }

        return {
            "success": True,
            "verified": True,
            "shipment": shipment_data
        }

    @classmethod
    def get_customer_tickets(cls, workspace_id: int, phone: str) -> dict:
        """Returns open and historical support tickets for the verified customer phone."""
        if not phone or not phone.strip():
            return {
                "success": False,
                "needs_phone": True,
                "error": "Please provide your registered 10-digit phone number."
            }

        norm_phone = normalize_phone(phone)
        from django.db.models import Q
        tickets = Ticket.objects.filter(
            workspace_id=workspace_id
        ).filter(
            Q(customer__normalized_phone=norm_phone) |
            Q(related_order__customer_phone=norm_phone)
        ).distinct().order_by("-created_at")

        tickets_data = []
        for t in tickets:
            tickets_data.append({
                "ticket_number": t.ticket_number,
                "subject": t.subject,
                "status": t.status,
                "priority": t.priority,
                "category": t.category,
                "assigned_team": t.assigned_team.name if t.assigned_team else "Unassigned",
                "created_at": t.created_at.strftime("%Y-%m-%d %H:%M"),
                "related_order": t.related_order.order_number if t.related_order else None
            })

        return {
            "success": True,
            "count": len(tickets_data),
            "tickets": tickets_data,
            "phone": norm_phone
        }

    @classmethod
    def get_return_refund_status(cls, workspace_id: int, query: str = "", phone: str = None) -> dict:
        """Returns ReturnRequest details for orders matching the caller's phone."""
        if not phone or not phone.strip():
            return {
                "success": False,
                "needs_phone": True,
                "error": "Please provide your registered 10-digit phone number."
            }

        norm_phone = normalize_phone(phone)
        qs = ReturnRequest.objects.filter(
            order__workspace_id=workspace_id,
            order__customer_phone=norm_phone
        ).select_related("order").order_by("-created_at")

        if query:
            clean_q = query.strip().upper()
            filtered = qs.filter(order__order_number__icontains=clean_q)
            if filtered.exists():
                qs = filtered

        results = []
        for r in qs:
            linked_ticket = Ticket.objects.filter(workspace_id=workspace_id, related_order=r.order).first()
            results.append({
                "order_number": r.order.order_number,
                "type": r.type,
                "status": r.status,
                "reason": r.reason,
                "refund_amount": f"₹{r.refund_amount:,.2f}",
                "refund_method": r.refund_method,
                "refund_status": r.refund_status,
                "expected_refund_by": r.expected_refund_by.strftime("%Y-%m-%d") if r.expected_refund_by else None,
                "created_at": r.created_at.strftime("%Y-%m-%d %H:%M"),
                "linked_ticket": linked_ticket.ticket_number if linked_ticket else None
            })

        return {
            "success": True,
            "has_return": len(results) > 0,
            "count": len(results),
            "returns": results,
            "return_request": results[0] if results else None,
            "phone": norm_phone
        }

    @classmethod
    def cancel_order(cls, workspace_id: int, order_number: str, phone: str, reason: str = "") -> dict:
        """
        Validates cancellation eligibility, updates Order status to CANCELLED,
        and creates/references a human support Ticket linked via related_order.
        """
        if not order_number or not order_number.strip():
            return {"success": False, "error": "No order number provided."}

        if not phone or not phone.strip():
            return {
                "success": False,
                "needs_phone": True,
                "error": "Please provide your registered 10-digit phone number to cancel an order."
            }

        norm_phone = normalize_phone(phone)
        order_num = order_number.strip().upper()
        order = Order.objects.filter(workspace_id=workspace_id, order_number__iexact=order_num).prefetch_related("items").first()

        if not order:
            return {"success": False, "error": f"Order '{order_num}' was not found in our records."}

        if norm_phone != order.customer_phone:
            return {
                "success": False,
                "verified": False,
                "error": "I couldn't verify that order against your phone number."
            }

        if not order.is_cancellable:
            if order.status == Order.Status.CANCELLED:
                existing_ticket = Ticket.objects.filter(
                    workspace_id=workspace_id,
                    related_order=order
                ).first()
                ticket_num = existing_ticket.ticket_number if existing_ticket else None
                return {
                    "success": True,
                    "cancelled": True,
                    "already_cancelled": True,
                    "order_number": order.order_number,
                    "ticket_number": ticket_num,
                    "message": f"Order {order.order_number} is already cancelled." + (f" Tracked under ticket #{ticket_num}." if ticket_num else "")
                }
            return {
                "success": False,
                "cancelled": False,
                "cancellable": False,
                "return_eligible": order.is_return_eligible,
                "status": order.status,
                "error": f"Order {order.order_number} is currently {order.status.lower()} and cannot be cancelled automatically. Once delivered, you may initiate a return."
            }

        # Check if an open ticket already exists for this order
        existing_ticket = Ticket.objects.filter(
            workspace_id=workspace_id,
            related_order=order,
            status__in=[Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS]
        ).first()

        if existing_ticket:
            order.status = Order.Status.CANCELLED
            order.cancelled_at = timezone.now()
            order.save(update_fields=["status", "cancelled_at", "updated_at"])

            return {
                "success": True,
                "cancelled": True,
                "order_number": order.order_number,
                "ticket_number": existing_ticket.ticket_number,
                "already_existed": True,
                "assigned_team": existing_ticket.assigned_team.name if existing_ticket.assigned_team else "Order Support",
                "message": f"Order {order.order_number} cancellation is already tracked under ticket #{existing_ticket.ticket_number}."
            }

        # Cancel the order
        order.status = Order.Status.CANCELLED
        order.cancelled_at = timezone.now()
        order.save(update_fields=["status", "cancelled_at", "updated_at"])

        cancel_team = Team.objects.filter(
            workspace_id=workspace_id,
            slug__in=["order-support", "tracking-delivery", "claims-disputes"]
        ).first() or Team.objects.filter(workspace_id=workspace_id, is_active=True).first()

        customer = order.customer
        if not customer:
            customer = Customer.objects.filter(workspace_id=workspace_id, normalized_phone=norm_phone).first()

        ticket = Ticket.objects.create(
            workspace_id=workspace_id,
            customer=customer,
            related_order=order,
            subject=f"Cancellation Request for Order #{order.order_number}",
            description=reason or f"Customer requested cancellation for Order #{order.order_number}.",
            category="Order Cancellation",
            priority=Ticket.Priority.HIGH,
            assigned_team=cancel_team,
            status=Ticket.Status.OPEN
        )

        TicketEvent.objects.create(
            ticket=ticket,
            event_type="ORDER_CANCELLED",
            description=f"Order {order.order_number} cancelled by customer via AI. Ticket created."
        )

        return {
            "success": True,
            "cancelled": True,
            "order_number": order.order_number,
            "ticket_number": ticket.ticket_number,
            "already_existed": False,
            "assigned_team": cancel_team.name if cancel_team else "Order Support",
            "message": f"Order {order.order_number} has been cancelled. Support ticket #{ticket.ticket_number} created."
        }

    # -------------------------------------------------------------------------
    # Backward Compatibility & External User-Configured Webhook Bridge
    # -------------------------------------------------------------------------

    @classmethod
    def lookup_order(cls, workspace_id: int, order_number: str, customer_phone: str = None, customer_email: str = None, phone: str = None) -> dict:
        """
        Unified lookup bridge: Checks real SQL DB (Order or Shipment) first,
        verifying phone or email if provided, and falls back to external user webhooks.
        """
        if not order_number or not order_number.strip():
            return {"success": False, "error": "No order number provided"}

        customer_phone = customer_phone or phone
        code = order_number.strip().upper()

        # 1. Check SQL Order
        order = Order.objects.filter(workspace_id=workspace_id, order_number__iexact=code).prefetch_related("items").first()
        if order:
            if customer_phone:
                norm_p = normalize_phone(customer_phone)
                if norm_p != order.customer_phone:
                    return {"success": False, "verified": False, "error": "I couldn't verify that order against your phone number."}
            elif customer_email:
                if order.customer_email and order.customer_email.lower() != customer_email.lower():
                    return {"success": False, "verified": False, "error": "Customer email does not match order record"}

            item_names = ", ".join([f"{i.name} (x{i.quantity})" for i in order.items.all()]) or "Store Item"
            return {
                "success": True,
                "verified": True,
                "order": {
                    "order_number": order.order_number,
                    "customer_name": order.customer_name,
                    "customer_phone": order.customer_phone,
                    "customer_email": order.customer_email,
                    "item": item_names,
                    "items": [{"name": i.name, "quantity": i.quantity, "unit_price": float(i.unit_price)} for i in order.items.all()],
                    "amount": f"₹{order.total:,.2f}",
                    "total": float(order.total),
                    "currency": order.currency,
                    "status": order.status,
                    "payment_method": order.payment_method,
                    "payment_status": order.payment_status,
                    "carrier": order.carrier or "Standard Courier",
                    "estimated_delivery": order.estimated_delivery.strftime("%Y-%m-%d") if order.estimated_delivery else "Delivered",
                    "can_cancel": order.is_cancellable,
                    "can_return": order.is_return_eligible,
                },
                "source": "sql_orders_database"
            }

        # 2. Check SQL Shipment
        shipment = Shipment.objects.filter(workspace_id=workspace_id, awb__iexact=code).prefetch_related("events").first()
        if shipment:
            if customer_phone:
                norm_p = normalize_phone(customer_phone)
                if norm_p not in (shipment.receiver_phone, shipment.sender_phone):
                    return {"success": False, "verified": False, "error": "I couldn't verify that order against your phone number."}

            latest_event = shipment.events.order_by("-occurred_at").first()
            return {
                "success": True,
                "verified": True,
                "order": {
                    "order_number": shipment.awb,
                    "awb": shipment.awb,
                    "item": f"Consignment ({shipment.weight_kg} kg) - {shipment.service_type}",
                    "amount": f"₹{shipment.cod_amount:,.2f}" if shipment.cod_amount else "Prepaid",
                    "status": shipment.status,
                    "carrier": f"ExpressBeas Logistics ({shipment.service_type})",
                    "estimated_delivery": shipment.estimated_delivery.strftime("%d %b %Y") if shipment.estimated_delivery else "Completed",
                    "origin": shipment.origin_city,
                    "destination": shipment.destination_city,
                    "last_scan": f"{latest_event.occurred_at.strftime('%d %b %Y, %I:%M %p')} - {latest_event.status} ({latest_event.location})" if latest_event else shipment.current_location,
                    "can_cancel": False,
                    "can_return": False,
                },
                "source": "sql_shipment_database"
            }

        # 3. External Webhook Fallback
        wh_res = cls._try_external_webhook(workspace_id=workspace_id, code=code, email=customer_email)
        if wh_res.get("success"):
            return wh_res

        ws = Workspace.objects.filter(id=workspace_id).first()
        store_display = ws.name if ws else "our store"
        return {
            "success": False,
            "error": f"Order or AWB '{code}' was not found in {store_display} dispatch records."
        }

    @classmethod
    def _try_external_webhook(cls, workspace_id: int, code: str, email: str = None) -> dict:
        """Queries external user-configured webhook endpoint if present."""
        try:
            active_wh = WorkspaceWebhook.objects.filter(
                workspace_id=workspace_id,
                is_active=True,
                webhook_type__in=[WorkspaceWebhook.WebhookType.ORDERS, WorkspaceWebhook.WebhookType.TRACKING]
            ).first()

            target_url = active_wh.url if active_wh else None
            secret_key = active_wh.secret_key if active_wh else None

            settings_obj = WorkspaceSettings.objects.filter(workspace_id=workspace_id).first()
            if not target_url and settings_obj and settings_obj.orders_api_webhook_url:
                target_url = settings_obj.orders_api_webhook_url
                secret_key = settings_obj.orders_api_secret_key

            if target_url and is_safe_url(target_url):
                params = {"order_id": code, "awb": code}
                if email:
                    params["email"] = email
                query_str = urllib.parse.urlencode(params)
                sep = "&" if "?" in target_url else "?"
                full_url = f"{target_url}{sep}{query_str}"

                timestamp_str = str(int(time.time()))
                headers = {
                    "User-Agent": "SupportoAI-ToolRunner/2.0",
                    "X-Supporto-Timestamp": timestamp_str
                }
                if secret_key:
                    headers["Authorization"] = f"Bearer {secret_key}"

                req = urllib.request.Request(full_url, headers=headers)
                with urllib.request.urlopen(req, timeout=3.0) as resp:
                    if resp.status == 200:
                        payload = json.loads(resp.read().decode("utf-8"))
                        if "order" in payload and payload["order"]:
                            return {"success": True, "order": payload["order"], "source": "external_webhook"}
                        if "tracking" in payload and payload["tracking"]:
                            return {"success": True, "order": payload["tracking"], "source": "external_carrier_api"}
        except Exception as e:
            logger.warning(f"External webhook query failed for workspace {workspace_id}: {e}")
        return {"success": False}

    # -------------------------------------------------------------------------
    # Knowledge Base, Escalation, & Ticket Management
    # -------------------------------------------------------------------------

    @staticmethod
    def search_knowledge_base(workspace_id: int, query: str) -> dict:
        results = rag_service.retrieve_context(workspace_id=workspace_id, query=query, top_k=3)
        return {
            "success": True,
            "count": len(results),
            "results": results
        }

    @staticmethod
    def create_ticket(workspace_id: int, customer_id: int, subject: str, description: str, priority: str = "MEDIUM", category: str = "General Support") -> dict:
        try:
            customer = Customer.objects.get(id=customer_id, workspace_id=workspace_id)
            valid_priority = priority if priority in Ticket.Priority.values else Ticket.Priority.MEDIUM

            ticket = Ticket.objects.create(
                workspace_id=workspace_id,
                customer=customer,
                subject=subject[:255],
                description=description,
                priority=valid_priority,
                category=category[:100],
                status=Ticket.Status.OPEN
            )
            TicketEvent.objects.create(
                ticket=ticket,
                event_type="AI_CREATED",
                description=f"Ticket created automatically by AI Agent. Priority: {ticket.priority}"
            )
            return {
                "success": True,
                "ticket_id": ticket.id,
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "priority": ticket.priority
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def get_ticket_status(workspace_id: int, ticket_number: str) -> dict:
        try:
            ticket = Ticket.objects.get(workspace_id=workspace_id, ticket_number=ticket_number.strip().upper())
            return {
                "success": True,
                "ticket_number": ticket.ticket_number,
                "subject": ticket.subject,
                "status": ticket.status,
                "priority": ticket.priority,
                "assigned_team": ticket.assigned_team.name if ticket.assigned_team else "Unassigned",
                "created_at": ticket.created_at.strftime("%Y-%m-%d %H:%M")
            }
        except Ticket.DoesNotExist:
            return {"success": False, "error": f"Ticket '{ticket_number}' not found."}

    @staticmethod
    def assign_ticket(workspace_id: int, ticket_id: int, team_id: int) -> dict:
        try:
            ticket = Ticket.objects.get(id=ticket_id, workspace_id=workspace_id)
            team = Team.objects.get(id=team_id, workspace_id=workspace_id, is_active=True)

            prev_team = ticket.assigned_team
            ticket.assigned_team = team
            ticket.save(update_fields=["assigned_team", "updated_at"])

            TicketAssignment.objects.create(
                ticket=ticket,
                previous_team=prev_team,
                new_team=team,
                reason="Assigned by AI Agent"
            )
            TicketEvent.objects.create(
                ticket=ticket,
                event_type="TEAM_ASSIGNED",
                description=f"Assigned to team '{team.name}' by AI Agent."
            )
            return {"success": True, "ticket_number": ticket.ticket_number, "assigned_team": team.name}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def _resolve_escalation_team(workspace_id: int, intent: str, reason: str):
        reason_lower = (reason or "").lower()
        if intent == "BILLING" or any(w in reason_lower for w in ["double", "billing", "charge", "deducted", "refund", "invoice", "payment", "card"]):
            team = Team.objects.filter(
                workspace_id=workspace_id,
                slug__in=["billing-support", "enterprise-billing", "claims-disputes", "quality-refunds"]
            ).first()
            if team:
                return team
        elif intent == "TECHNICAL" or any(w in reason_lower for w in ["crash", "api", "bug", "error", "down", "freeze", "glitch"]):
            team = Team.objects.filter(
                workspace_id=workspace_id,
                slug__in=["technical-support", "dev-support"]
            ).first()
            if team:
                return team
        elif intent in ["SHIPPING", "RETURNS", "DEFECT"] or any(w in reason_lower for w in ["ship", "tracking", "awb", "lost", "delay", "damage"]):
            team = Team.objects.filter(
                workspace_id=workspace_id,
                slug__in=["tracking-delivery", "order-support", "claims-disputes", "hyperlocal-delivery"]
            ).first()
            if team:
                return team
        return Team.objects.filter(workspace_id=workspace_id, is_active=True).first()

    @classmethod
    def escalate_to_human(cls, workspace_id: int, conversation_id: int, reason: str, customer_message: str = "") -> dict:
        try:
            conversation = Conversation.objects.get(id=conversation_id, workspace_id=workspace_id)
            conversation.is_escalated = True
            is_critical = conversation.urgency == "CRITICAL" or any(w in reason.lower() for w in ["double", "billing", "urgent", "twice", "fraud", "scam", "deducted"])
            if is_critical:
                conversation.urgency = "CRITICAL"
            conversation.save(update_fields=["is_escalated", "urgency", "updated_at"])

            assigned_team = cls._resolve_escalation_team(workspace_id, conversation.intent or "", reason)

            # Check if ticket already exists for this conversation
            existing = Ticket.objects.filter(conversation=conversation).first()
            if existing:
                needs_update = False
                if is_critical and existing.priority != Ticket.Priority.CRITICAL:
                    existing.priority = Ticket.Priority.CRITICAL
                    needs_update = True
                if assigned_team and existing.assigned_team != assigned_team:
                    prev_team = existing.assigned_team
                    existing.assigned_team = assigned_team
                    needs_update = True
                    TicketAssignment.objects.create(
                        ticket=existing,
                        previous_team=prev_team,
                        new_team=assigned_team,
                        reason=f"Reassigned on new escalation: {reason[:100]}"
                    )
                    TicketEvent.objects.create(
                        ticket=existing,
                        event_type="REASSIGNED",
                        description=f"Ticket escalated & reassigned to '{assigned_team.name}': {reason[:100]}"
                    )
                if needs_update:
                    existing.save(update_fields=["priority", "assigned_team", "updated_at"])

                return {
                    "success": True,
                    "escalated": True,
                    "ticket_number": existing.ticket_number,
                    "priority": existing.priority,
                    "assigned_team": existing.assigned_team.name if existing.assigned_team else "Billing Support",
                    "already_existed": True,
                    "updated": needs_update
                }

            if not assigned_team:
                assigned_team = Team.objects.filter(workspace_id=workspace_id, is_active=True).first()

            intent = conversation.intent or "SUPPORT"
            category_map = {
                "BILLING": "Billing & Payments",
                "TECHNICAL": "Technical Support",
                "SHIPPING": "Shipping & Logistics",
                "RETURNS": "Returns & Exchanges",
                "DEFECT": "Damaged & Defective",
                "HUMAN_HANDOFF": "Customer Escalation",
            }
            ticket_category = category_map.get(intent, "General Support")

            ticket_priority = Ticket.Priority.CRITICAL if is_critical else Ticket.Priority.HIGH
            description_text = customer_message.strip() if customer_message else reason.strip()

            ticket = Ticket.objects.create(
                workspace_id=workspace_id,
                customer=conversation.customer,
                conversation=conversation,
                subject=f"Urgent: {ticket_category} Inquiry",
                description=description_text,
                priority=ticket_priority,
                category=ticket_category,
                assigned_team=assigned_team,
                status=Ticket.Status.OPEN
            )

            TicketEvent.objects.create(
                ticket=ticket,
                event_type="ESCALATED",
                description=f"Conversation escalated to human ticket. Reason: {reason}"
            )

            return {
                "success": True,
                "escalated": True,
                "ticket_id": ticket.id,
                "ticket_number": ticket.ticket_number,
                "priority": ticket_priority,
                "assigned_team": assigned_team.name if assigned_team else "Billing Support"
            }
        except Exception as e:
            logger.error(f"Error escalating conversation: {e}")
            return {"success": False, "error": str(e)}

tool_registry = ToolRegistry()
