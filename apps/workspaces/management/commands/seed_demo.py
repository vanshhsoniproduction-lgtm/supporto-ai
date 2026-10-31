"""
seed_demo.py - Comprehensive multi-tenant demo seeder for Supporto AI.
Seeds real SQL data layers for:
  1. ShopEase (Electronics E-commerce)
  2. ExpressBeas (Logistics & Supply-Chain Network)
  (TechNova & FreshMart available via --all flag)

Features:
- Idempotent execution inside transaction.atomic
- Superuser: admin@admin.com / admin (staff, platform admin)
- Workspace staff:
  * ShopEase: owner@shopease.com / ShopEase@123, agent@shopease.com / Agent@123
  * ExpressBeas: owner@expressbeas.in / ExpressBeas@123, agent@expressbeas.in / Agent@123
- Phone-verified customer dataset:
  * Customer A: Vansh Soni (6367743066)
  * Customer B: Riya Sharma (9571538144)
- 3 weeks of historical analytics & ticket logs
- Honest external webhook configuration (zero fake mock endpoints)
"""
import uuid
from datetime import timedelta, datetime, timezone as dt_tz
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from apps.workspaces.models import (
    Workspace,
    WorkspaceMembership,
    WorkspaceSettings,
    WorkspaceAuthorizedEmail,
    WorkspaceWebhook,
)
from apps.teams.models import Team, TeamMembership
from apps.customers.models import Customer
from apps.conversations.models import Conversation, Message
from apps.tickets.models import Ticket, TicketComment, TicketEvent, TicketAssignment
from apps.knowledge_base.models import KnowledgeDocument
from apps.knowledge_base.services.document_processor import document_processor
from apps.ai_engine.models import AgentConfiguration
from apps.voice_support.models import VoiceConfiguration
from apps.emails.models import MailboxConnection, InboundEmail
from apps.orders.models import Order, OrderItem, Shipment, ShipmentEvent, ReturnRequest
from apps.orders.utils import normalize_phone

User = get_user_model()

OWNER_EMAILS = [
    "vanshhsoni.production@gmail.com",
    "sonivanshmaster@gmail.com",
    "vanshhsoni@gmail.com",
]

FIXED_WORKSPACE_KEYS = {
    "shopease": uuid.UUID("205efaa9-4d66-4903-b6f6-cccb701c8668"),
    "expressbeas": uuid.UUID("4ecc8df2-e72a-49e5-bb37-bb0211a39a05"),
    "technova": uuid.UUID("c10541fd-b19b-4aa5-98b6-1fcdbbeab550"),
    "freshmart": uuid.UUID("7f439472-80e5-4058-ab91-d884855ef2a5"),
}


class Command(BaseCommand):
    help = "Seeds deterministic demo dataset for Supporto AI (ShopEase & ExpressBeas)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Wipe all existing database records before seeding.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Seed all 4 workspaces (including TechNova and FreshMart). Default seeds only ShopEase and ExpressBeas.",
        )

    def handle(self, *args, **options):
        reset = options.get("reset", False)
        seed_all = options.get("all", False)

        if reset:
            self.stdout.write(self.style.WARNING("[!] Running database reset (--reset)..."))
            call_command("clear_db", "--yes")

        with transaction.atomic():
            self._seed_platform_admin()
            self._seed_workspaces(seed_all=seed_all)

        self._print_summary(seed_all=seed_all)

    # -------------------------------------------------------------------------
    # 0. Platform Superuser & Admin
    # -------------------------------------------------------------------------

    def _seed_platform_admin(self):
        admin_user, created = User.objects.get_or_create(
            email="admin@admin.com",
            defaults={
                "username": "admin@admin.com",
                "first_name": "Platform",
                "last_name": "Admin",
                "is_staff": True,
                "is_superuser": True,
                "platform_role": User.PlatformRole.PLATFORM_ADMIN,
            }
        )
        admin_user.set_password("admin")
        admin_user.is_staff = True
        admin_user.is_superuser = True
        admin_user.platform_role = User.PlatformRole.PLATFORM_ADMIN
        admin_user.save()

        self.stdout.write(self.style.SUCCESS("  [+] Platform superuser ready (admin@admin.com / admin)"))
        self.stdout.write(self.style.WARNING("  [!] SECURITY WARNING: Default superuser admin@admin.com:admin created. Change password for public deployment!"))

    # -------------------------------------------------------------------------
    # 1. Workspaces, Staff, Settings & Real SQL Data Layer
    # -------------------------------------------------------------------------

    def _seed_workspaces(self, seed_all=False):
        now = timezone.now()

        # ---------------------------------------------------------------------
        # Workspace 1: ShopEase (E-commerce Storefront)
        # ---------------------------------------------------------------------
        shopease, _ = Workspace.objects.get_or_create(
            slug="shopease",
            defaults={
                "name": "ShopEase",
                "public_key": FIXED_WORKSPACE_KEYS["shopease"],
                "status": Workspace.Status.ACTIVE,
            }
        )
        shopease.public_key = FIXED_WORKSPACE_KEYS["shopease"]
        shopease.status = Workspace.Status.ACTIVE
        shopease.save()

        # Settings
        settings_se, _ = WorkspaceSettings.objects.get_or_create(
            workspace=shopease,
            defaults={
                "company_website": "https://shopease.example.com",
                "support_email": "vanshhsoni.production@gmail.com",
                "welcome_message": "Welcome to ShopEase Support! How can our AI assistant help you with your order, returns, or billing today?",
                "sla_urgent_minutes": 15,
                "sla_standard_hours": 12,
                "ticket_auto_assignment": True,
            }
        )
        settings_se.orders_api_webhook_url = ""  # Zero fake mock webhooks
        settings_se.save()

        AgentConfiguration.objects.get_or_create(
            workspace=shopease,
            defaults={
                "system_prompt": (
                    "You are Supporto AI for ShopEase. Empathize with the customer, keep responses concise, "
                    "and refer strictly to ShopEase policies and verified order records. For double charges, immediately escalate to Billing Support."
                ),
                "temperature": 0.1,
                "max_tokens": 200,
            }
        )

        VoiceConfiguration.objects.get_or_create(
            workspace=shopease,
            defaults={"voice_name": "af_sarah", "speed": 1.05}
        )

        MailboxConnection.objects.get_or_create(
            workspace=shopease,
            email_address="support@shopease.com",
            defaults={"status": MailboxConnection.Status.ACTIVE}
        )

        # Teams
        team_se_orders, _ = Team.objects.get_or_create(
            workspace=shopease, slug="order-support",
            defaults={"name": "Order Support", "description": "Handles fulfillment, order tracking, and cancellations."}
        )
        team_se_billing, _ = Team.objects.get_or_create(
            workspace=shopease, slug="billing-support",
            defaults={"name": "Billing Support", "description": "Handles payments, refunds, double charges, and disputes."}
        )
        team_se_tech, _ = Team.objects.get_or_create(
            workspace=shopease, slug="technical-support",
            defaults={"name": "Technical Support", "description": "Handles app errors, firmware bugs, and account issues."}
        )

        # Staff Users
        se_owner = self._create_user("owner@shopease.com", "ShopEase@123", "ShopEase", "Owner")
        se_agent = self._create_user("agent@shopease.com", "Agent@123", "Alex", "Agent")
        WorkspaceMembership.objects.get_or_create(workspace=shopease, user=se_owner, defaults={"role": WorkspaceMembership.Role.OWNER, "is_active": True})
        WorkspaceMembership.objects.get_or_create(workspace=shopease, user=se_agent, defaults={"role": WorkspaceMembership.Role.AGENT, "is_active": True})

        # Add Google login owners
        for email in OWNER_EMAILS:
            user = self._create_user(email, "GoogleLoginUser@123", "Vansh", "Soni")
            WorkspaceMembership.objects.get_or_create(workspace=shopease, user=user, defaults={"role": WorkspaceMembership.Role.OWNER, "is_active": True})
            WorkspaceAuthorizedEmail.objects.get_or_create(
                workspace=shopease, email=email,
                defaults={"normalized_email": email.lower().strip(), "assigned_role": WorkspaceMembership.Role.OWNER, "status": WorkspaceAuthorizedEmail.Status.AUTHORIZED}
            )

        TeamMembership.objects.get_or_create(team=team_se_orders, user=se_agent, defaults={"role": TeamMembership.Role.MEMBER})
        TeamMembership.objects.get_or_create(team=team_se_billing, user=se_agent, defaults={"role": TeamMembership.Role.MEMBER})
        TeamMembership.objects.get_or_create(team=team_se_tech, user=se_agent, defaults={"role": TeamMembership.Role.MEMBER})

        # RAG Knowledge Base Docs
        self._seed_shopease_faqs(shopease)

        # Customers & SQL Orders
        self._seed_shopease_orders_and_customers(shopease, team_se_orders, team_se_billing, se_agent, now)

        self.stdout.write("  [+] ShopEase workspace & SQL data layer seeded.")

        # ---------------------------------------------------------------------
        # Workspace 2: ExpressBeas (Courier & Logistics)
        # ---------------------------------------------------------------------
        expressbeas, _ = Workspace.objects.get_or_create(
            slug="expressbeas",
            defaults={
                "name": "ExpressBeas",
                "public_key": FIXED_WORKSPACE_KEYS["expressbeas"],
                "status": Workspace.Status.ACTIVE,
            }
        )
        expressbeas.public_key = FIXED_WORKSPACE_KEYS["expressbeas"]
        expressbeas.status = Workspace.Status.ACTIVE
        expressbeas.save()

        # Settings
        settings_eb, _ = WorkspaceSettings.objects.get_or_create(
            workspace=expressbeas,
            defaults={
                "company_website": "https://expressbeas.in",
                "support_email": "vanshhsoni.production@gmail.com",
                "welcome_message": "Welcome to ExpressBeas Support! Track your shipment AWB, report a delayed parcel, or schedule a pickup. How can we help today?",
                "sla_urgent_minutes": 10,
                "sla_standard_hours": 8,
                "ticket_auto_assignment": True,
            }
        )
        settings_eb.orders_api_webhook_url = ""  # Zero fake mock webhooks
        settings_eb.save()

        AgentConfiguration.objects.get_or_create(
            workspace=expressbeas,
            defaults={
                "system_prompt": (
                    "You are Supporto AI for ExpressBeas Logistics. Help customers track Air Waybill (AWB) consignment numbers, "
                    "report delivery delays or damages, and schedule pickups. Answer accurately from verified consignment timelines."
                ),
                "temperature": 0.1,
                "max_tokens": 200,
            }
        )

        VoiceConfiguration.objects.get_or_create(
            workspace=expressbeas,
            defaults={"voice_name": "af_sarah", "speed": 1.05}
        )

        MailboxConnection.objects.get_or_create(
            workspace=expressbeas,
            email_address="support@expressbeas.in",
            defaults={"status": MailboxConnection.Status.ACTIVE}
        )

        # Teams
        team_eb_tracking, _ = Team.objects.get_or_create(
            workspace=expressbeas, slug="tracking-delivery",
            defaults={"name": "Tracking & Delivery", "description": "Handles live AWB tracking, delay investigations, and rider dispatch."}
        )
        team_eb_claims, _ = Team.objects.get_or_create(
            workspace=expressbeas, slug="claims-disputes",
            defaults={"name": "Claims & Disputes", "description": "Handles lost shipments, damaged packages, and insurance settlements."}
        )

        # Staff Users
        eb_owner = self._create_user("owner@expressbeas.in", "ExpressBeas@123", "ExpressBeas", "Owner")
        eb_agent = self._create_user("agent@expressbeas.in", "Agent@123", "Priya", "Agent")
        WorkspaceMembership.objects.get_or_create(workspace=expressbeas, user=eb_owner, defaults={"role": WorkspaceMembership.Role.OWNER, "is_active": True})
        WorkspaceMembership.objects.get_or_create(workspace=expressbeas, user=eb_agent, defaults={"role": WorkspaceMembership.Role.AGENT, "is_active": True})

        # Add Google login owners
        for email in OWNER_EMAILS:
            user = self._create_user(email, "GoogleLoginUser@123", "Vansh", "Soni")
            WorkspaceMembership.objects.get_or_create(workspace=expressbeas, user=user, defaults={"role": WorkspaceMembership.Role.OWNER, "is_active": True})
            WorkspaceAuthorizedEmail.objects.get_or_create(
                workspace=expressbeas, email=email,
                defaults={"normalized_email": email.lower().strip(), "assigned_role": WorkspaceMembership.Role.OWNER, "status": WorkspaceAuthorizedEmail.Status.AUTHORIZED}
            )

        TeamMembership.objects.get_or_create(team=team_eb_tracking, user=eb_agent, defaults={"role": TeamMembership.Role.MEMBER})
        TeamMembership.objects.get_or_create(team=team_eb_claims, user=eb_agent, defaults={"role": TeamMembership.Role.MEMBER})

        # RAG Knowledge Base Docs
        self._seed_expressbeas_faqs(expressbeas)

        # Customers & SQL Shipments
        self._seed_expressbeas_shipments_and_customers(expressbeas, team_eb_tracking, team_eb_claims, eb_agent, now)

        self.stdout.write("  [+] ExpressBeas workspace & SQL carrier network seeded.")

        # ---------------------------------------------------------------------
        # Optional: TechNova & FreshMart (if --all is passed)
        # ---------------------------------------------------------------------
        if seed_all:
            self._seed_technova_and_freshmart(now)

    # -------------------------------------------------------------------------
    # Helper: Create or retrieve user
    # -------------------------------------------------------------------------

    def _create_user(self, email, password, first_name="", last_name=""):
        user, _ = User.objects.get_or_create(
            email=email,
            defaults={
                "username": email,
                "first_name": first_name,
                "last_name": last_name,
            }
        )
        user.set_password(password)
        user.first_name = first_name
        user.last_name = last_name
        user.save()
        return user

    # -------------------------------------------------------------------------
    # ShopEase FAQs & Knowledge Base
    # -------------------------------------------------------------------------

    def _seed_shopease_faqs(self, workspace):
        faqs = [
            (
                "ShopEase Return & Refund Policy",
                "What is the return and refund policy at ShopEase?",
                "ShopEase offers a 30-day hassle-free return window for electronics in original packaging. Once a return request is submitted, a reverse pickup is scheduled within 24-48 hours. After quality inspection, refunds are credited to the original payment method within 3-5 business days."
            ),
            (
                "Order Cancellation Policy",
                "Can I cancel my ShopEase order?",
                "Orders in 'Placed' or 'Processing' status can be cancelled immediately through chat or your order dashboard. Once an order is dispatched or In Transit with a courier carrier, it cannot be cancelled mid-shipment. In that case, you can initiate a return after doorstep delivery."
            ),
            (
                "Double Charge & Billing Inquiries",
                "What should I do if my card is charged twice?",
                "If an unauthorized or duplicate charge occurs, our AI immediately escalates the case to our dedicated Billing Support team with Critical priority. A human billing specialist reviews the payment gateway logs and initiates an immediate reversal within 15 minutes."
            ),
            (
                "Standard Shipping & Delivery",
                "How long does delivery take?",
                "Standard orders are delivered in 2-4 business days via FedEx, Bluedart, or Delhivery. Orders above ₹999 qualify for complimentary express delivery."
            ),
        ]
        for title, q, content in faqs:
            doc, created = KnowledgeDocument.objects.get_or_create(
                workspace=workspace,
                title=title,
                defaults={
                    "doc_type": KnowledgeDocument.DocType.FAQ,
                    "question": q,
                    "answer": content,
                    "content": f"Question: {q}\n\nAnswer: {content}",
                    "is_active": True,
                }
            )
            if created or not doc.chunks.exists():
                doc.question = q
                doc.answer = content
                doc.content = f"Question: {q}\n\nAnswer: {content}"
                doc.is_active = True
                doc.save()
                document_processor.chunk_and_index(doc)

    # -------------------------------------------------------------------------
    # ExpressBeas FAQs & Knowledge Base
    # -------------------------------------------------------------------------

    def _seed_expressbeas_faqs(self, workspace):
        faqs = [
            (
                "AWB Tracking & Status Scans",
                "How do I track my ExpressBeas shipment with AWB number?",
                "Enter your 15-digit AWB number (e.g. 152785863851740) in the chat or visit expressbeas.in/track. Scans are recorded at each sort facility: Booked -> Hub Inward -> In Transit -> Out for Delivery -> Delivered with OTP verification."
            ),
            (
                "Delivery Timelines & Express Slots",
                "How long does delivery take for standard and air shipments?",
                "Intra-city deliveries take 24 hours. Metro-to-metro surface shipments arrive in 2-3 business days. Air Express arrives within 24-48 hours. Delayed parcels due to weather or road closures receive automated tracking remarks."
            ),
            (
                "Lost or Damaged Parcel Claim",
                "What is the claim process for damaged or lost goods?",
                "Claims must be lodged within 7 days of scheduled delivery. Provide your AWB consignment number and damage photos. Our Claims & Disputes desk investigates within 48 business hours, and insurance settlements are processed directly."
            ),
            (
                "Schedule a Doorstep Pickup",
                "Can I schedule a doorstep courier pickup?",
                "Yes. Pickups scheduled before 12:00 PM are completed the same day between 2:00 PM and 6:00 PM. Our dispatch rider weighs the package and generates an official AWB receipt upon collection."
            ),
        ]
        for title, q, content in faqs:
            doc, created = KnowledgeDocument.objects.get_or_create(
                workspace=workspace,
                title=title,
                defaults={
                    "doc_type": KnowledgeDocument.DocType.FAQ,
                    "question": q,
                    "answer": content,
                    "content": f"Question: {q}\n\nAnswer: {content}",
                    "is_active": True,
                }
            )
            if created or not doc.chunks.exists():
                doc.question = q
                doc.answer = content
                doc.content = f"Question: {q}\n\nAnswer: {content}"
                doc.is_active = True
                doc.save()
                document_processor.chunk_and_index(doc)

    # -------------------------------------------------------------------------
    # ShopEase SQL Orders & Demo Customers
    # -------------------------------------------------------------------------

    def _seed_shopease_orders_and_customers(self, workspace, team_orders, team_billing, agent_user, now):
        # 1. Customer A: Vansh Soni
        cust_a, _ = Customer.objects.get_or_create(
            workspace=workspace,
            normalized_phone="6367743066",
            defaults={
                "name": "Vansh Soni",
                "email": "vansh.soni@example.com",
                "phone": "+91 63677 43066",
                "source": Customer.Source.WIDGET,
                "is_anonymous": False,
            }
        )

        # 2. Customer B: Riya Sharma
        cust_b, _ = Customer.objects.get_or_create(
            workspace=workspace,
            normalized_phone="9571538144",
            defaults={
                "name": "Riya Sharma",
                "email": "riya.sharma@example.com",
                "phone": "+91 95715 38144",
                "source": Customer.Source.WIDGET,
                "is_anonymous": False,
            }
        )

        # Order SE-84920 (Delivered + Return Scheduled + Support Ticket)
        ord_84920, _ = Order.objects.get_or_create(
            workspace=workspace,
            order_number="SE-84920",
            defaults={
                "customer": cust_a,
                "customer_name": "Vansh Soni",
                "customer_phone": "6367743066",
                "customer_email": "vansh.soni@example.com",
                "status": Order.Status.DELIVERED,
                "payment_method": Order.PaymentMethod.CARD,
                "payment_status": Order.PaymentStatus.PAID,
                "subtotal": Decimal("4999.00"),
                "shipping_fee": Decimal("0.00"),
                "discount": Decimal("0.00"),
                "total": Decimal("4999.00"),
                "shipping_address": "12, Civil Lines",
                "pincode": "302006",
                "placed_at": now - timedelta(days=5),
                "estimated_delivery": now - timedelta(days=3),
                "delivered_at": now - timedelta(days=3),
                "carrier": "FedEx Express (FX-94001118)",
                "return_eligible_until": now + timedelta(days=27),
            }
        )
        OrderItem.objects.get_or_create(
            order=ord_84920, sku="ANC-HP-01",
            defaults={"name": "Wireless Noise-Canceling Headphones", "quantity": 1, "unit_price": Decimal("4999.00")}
        )

        # ReturnRequest for SE-84920
        ret_84920, _ = ReturnRequest.objects.get_or_create(
            order=ord_84920,
            defaults={
                "type": ReturnRequest.Type.RETURN_AND_REFUND,
                "reason": "Sound profile too bass heavy for my preference",
                "status": ReturnRequest.Status.PICKUP_SCHEDULED,
                "refund_amount": Decimal("4999.00"),
                "refund_method": "Original Payment Method (Card ending 4242)",
                "refund_status": ReturnRequest.RefundStatus.PENDING,
                "expected_refund_by": now + timedelta(days=2),
            }
        )

        # Support Ticket for SE-84920 with 3 events
        ticket_84920, t_created = Ticket.objects.get_or_create(
            workspace=workspace,
            ticket_number="TK-84920",
            defaults={
                "customer": cust_a,
                "related_order": ord_84920,
                "subject": "Return Request for Order #SE-84920",
                "description": "Customer requested return for Wireless Noise-Canceling Headphones. Return request approved and reverse pickup scheduled.",
                "priority": Ticket.Priority.MEDIUM,
                "category": "Returns & Exchanges",
                "status": Ticket.Status.IN_PROGRESS,
                "assigned_team": team_orders,
                "assigned_agent": agent_user,
            }
        )
        if t_created:
            TicketEvent.objects.create(ticket=ticket_84920, event_type="RETURN_REQUESTED", description="Return request submitted by customer via chat widget.", created_at=now - timedelta(days=2))
            TicketEvent.objects.create(ticket=ticket_84920, event_type="RETURN_APPROVED", description="Return request approved by Returns specialist.", created_at=now - timedelta(days=1))
            TicketEvent.objects.create(ticket=ticket_84920, event_type="PICKUP_SCHEDULED", description="Reverse pickup scheduled with courier for tomorrow.", created_at=now - timedelta(hours=6))

        # Order SE-84921 (In Transit via Delhivery)
        ord_84921, _ = Order.objects.get_or_create(
            workspace=workspace,
            order_number="SE-84921",
            defaults={
                "customer": cust_a,
                "customer_name": "Vansh Soni",
                "customer_phone": "6367743066",
                "customer_email": "vansh.soni@example.com",
                "status": Order.Status.IN_TRANSIT,
                "payment_method": Order.PaymentMethod.CARD,
                "payment_status": Order.PaymentStatus.PAID,
                "subtotal": Decimal("64999.00"),
                "shipping_fee": Decimal("0.00"),
                "discount": Decimal("0.00"),
                "total": Decimal("64999.00"),
                "shipping_address": "12, Civil Lines",
                "pincode": "302006",
                "placed_at": now - timedelta(days=2),
                "estimated_delivery": now + timedelta(days=1),
                "carrier": "Delhivery (AWB DEL8492100)",
            }
        )
        OrderItem.objects.get_or_create(
            order=ord_84921, sku="LAP-AIR-15",
            defaults={"name": "Ultra-Slim Laptop Air 15\"", "quantity": 1, "unit_price": Decimal("64999.00")}
        )

        # Order SE-84922 (Processing & Cancellable)
        ord_84922, _ = Order.objects.get_or_create(
            workspace=workspace,
            order_number="SE-84922",
            defaults={
                "customer": cust_a,
                "customer_name": "Vansh Soni",
                "customer_phone": "6367743066",
                "customer_email": "vansh.soni@example.com",
                "status": Order.Status.PROCESSING,
                "payment_method": Order.PaymentMethod.UPI,
                "payment_status": Order.PaymentStatus.PAID,
                "subtotal": Decimal("2499.00"),
                "shipping_fee": Decimal("0.00"),
                "discount": Decimal("0.00"),
                "total": Decimal("2499.00"),
                "shipping_address": "12, Civil Lines",
                "pincode": "302006",
                "placed_at": now - timedelta(minutes=45),
                "estimated_delivery": now + timedelta(days=3),
                "carrier": "Pending Fulfillment Dispatch",
            }
        )
        OrderItem.objects.get_or_create(
            order=ord_84922, sku="WATCH-PRO-02",
            defaults={"name": "Smart Fitness Watch Pro", "quantity": 1, "unit_price": Decimal("2499.00")}
        )

        # Order SE-84923 (Delivered 40d ago - Return Expired)
        ord_84923, _ = Order.objects.get_or_create(
            workspace=workspace,
            order_number="SE-84923",
            defaults={
                "customer": cust_a,
                "customer_name": "Vansh Soni",
                "customer_phone": "6367743066",
                "customer_email": "vansh.soni@example.com",
                "status": Order.Status.DELIVERED,
                "payment_method": Order.PaymentMethod.UPI,
                "payment_status": Order.PaymentStatus.PAID,
                "subtotal": Decimal("1298.00"),
                "shipping_fee": Decimal("0.00"),
                "discount": Decimal("0.00"),
                "total": Decimal("1298.00"),
                "shipping_address": "12, Civil Lines",
                "pincode": "302006",
                "placed_at": now - timedelta(days=42),
                "estimated_delivery": now - timedelta(days=40),
                "delivered_at": now - timedelta(days=40),
                "carrier": "Bluedart Ground",
                "return_eligible_until": now - timedelta(days=10),  # Expired
            }
        )
        OrderItem.objects.get_or_create(
            order=ord_84923, sku="CASE-SIL-01",
            defaults={"name": "Silicon Phone Case", "quantity": 1, "unit_price": Decimal("499.00")}
        )
        OrderItem.objects.get_or_create(
            order=ord_84923, sku="CHG-65W-01",
            defaults={"name": "65W Fast Charger", "quantity": 1, "unit_price": Decimal("799.00")}
        )

        # Customer B: Riya Sharma Orders
        ord_85001, _ = Order.objects.get_or_create(
            workspace=workspace,
            order_number="SE-85001",
            defaults={
                "customer": cust_b,
                "customer_name": "Riya Sharma",
                "customer_phone": "9571538144",
                "customer_email": "riya.sharma@example.com",
                "status": Order.Status.OUT_FOR_DELIVERY,
                "payment_method": Order.PaymentMethod.UPI,
                "payment_status": Order.PaymentStatus.PAID,
                "subtotal": Decimal("3299.00"),
                "shipping_fee": Decimal("0.00"),
                "discount": Decimal("0.00"),
                "total": Decimal("3299.00"),
                "shipping_address": "45, Malviya Nagar",
                "pincode": "302017",
                "placed_at": now - timedelta(days=3),
                "estimated_delivery": now,
                "carrier": "Bluedart Express",
            }
        )
        OrderItem.objects.get_or_create(
            order=ord_85001, sku="SHOE-RN-07",
            defaults={"name": "Running Shoes (Size 7)", "quantity": 1, "unit_price": Decimal("3299.00")}
        )

        ord_85002, _ = Order.objects.get_or_create(
            workspace=workspace,
            order_number="SE-85002",
            defaults={
                "customer": cust_b,
                "customer_name": "Riya Sharma",
                "customer_phone": "9571538144",
                "customer_email": "riya.sharma@example.com",
                "status": Order.Status.CANCELLED,
                "payment_method": Order.PaymentMethod.UPI,
                "payment_status": Order.PaymentStatus.REFUNDED,
                "subtotal": Decimal("1899.00"),
                "shipping_fee": Decimal("0.00"),
                "discount": Decimal("0.00"),
                "total": Decimal("1899.00"),
                "shipping_address": "45, Malviya Nagar",
                "pincode": "302017",
                "placed_at": now - timedelta(days=6),
                "cancelled_at": now - timedelta(days=6, minutes=-20),
                "notes": "Cancelled by customer within 1-hour grace window. UPI refund completed.",
            }
        )
        OrderItem.objects.get_or_create(
            order=ord_85002, sku="SPK-BT-MINI",
            defaults={"name": "Bluetooth Speaker", "quantity": 1, "unit_price": Decimal("1899.00")}
        )

        # 3 Weeks of Historical Analytics Tickets
        self._seed_historical_tickets(workspace, [team_orders, team_billing], agent_user, now)

    # -------------------------------------------------------------------------
    # ExpressBeas SQL Shipments & Carrier Timeline Events
    # -------------------------------------------------------------------------

    def _seed_expressbeas_shipments_and_customers(self, workspace, team_tracking, team_claims, agent_user, now):
        # 1. Customer A: Vansh Soni
        cust_a, _ = Customer.objects.get_or_create(
            workspace=workspace,
            normalized_phone="6367743066",
            defaults={
                "name": "Vansh Soni",
                "email": "vansh.soni@example.com",
                "phone": "+91 63677 43066",
                "source": Customer.Source.WIDGET,
                "is_anonymous": False,
            }
        )

        # 2. Customer B: Riya Sharma
        cust_b, _ = Customer.objects.get_or_create(
            workspace=workspace,
            normalized_phone="9571538144",
            defaults={
                "name": "Riya Sharma",
                "email": "riya.sharma@example.com",
                "phone": "+91 95715 38144",
                "source": Customer.Source.WIDGET,
                "is_anonymous": False,
            }
        )

        # Consignment 152785863851740 (Delivered - Exact 6-event timeline from 20 Sep 2026)
        ship_1, created_s1 = Shipment.objects.get_or_create(
            workspace=workspace,
            awb="152785863851740",
            defaults={
                "service_type": Shipment.ServiceType.SURFACE,
                "weight_kg": Decimal("1.20"),
                "origin_city": "Ghaziabad",
                "destination_city": "Jaipur",
                "sender_name": "Cloudtail India",
                "sender_phone": "9811002233",
                "receiver_name": "Vansh Soni",
                "receiver_phone": "6367743066",
                "status": Shipment.Status.DELIVERED,
                "current_location": "Jaipur Delivery Center",
                "delivered_at": datetime(2026, 9, 22, 15, 42, tzinfo=dt_tz.utc),
            }
        )
        if created_s1 or not ship_1.events.exists():
            ShipmentEvent.objects.create(shipment=ship_1, status="Manifest Uploaded & Data Received", location="Ghaziabad Hub", occurred_at=datetime(2026, 9, 20, 9, 12, tzinfo=dt_tz.utc), remarks="Consignment electronic manifest received from seller.")
            ShipmentEvent.objects.create(shipment=ship_1, status="Pickup Done", location="Ghaziabad Facility", occurred_at=datetime(2026, 9, 20, 14, 30, tzinfo=dt_tz.utc), remarks="Package received from Cloudtail warehouse.")
            ShipmentEvent.objects.create(shipment=ship_1, status="In Transit", location="Delhi Main Sort Hub", occurred_at=datetime(2026, 9, 20, 21, 15, tzinfo=dt_tz.utc), remarks="Inward sorting scan completed.")
            ShipmentEvent.objects.create(shipment=ship_1, status="In Transit", location="Delhi Highway Dispatch", occurred_at=datetime(2026, 9, 21, 4, 20, tzinfo=dt_tz.utc), remarks="Dispatched in vehicle DL-1C-5012 to Jaipur.")
            ShipmentEvent.objects.create(shipment=ship_1, status="Reached at Destination", location="Jaipur Central Mother Hub", occurred_at=datetime(2026, 9, 21, 23, 45, tzinfo=dt_tz.utc), remarks="Arrival scan completed at destination mother hub.")
            ShipmentEvent.objects.create(shipment=ship_1, status="Delivered", location="Jaipur Delivery Center", occurred_at=datetime(2026, 9, 22, 15, 42, tzinfo=dt_tz.utc), remarks="Delivered to recipient with OTP verification.")

        # Consignment 152785863851741 (In Transit - Delayed at Delhi Sort Hub)
        ship_2, created_s2 = Shipment.objects.get_or_create(
            workspace=workspace,
            awb="152785863851741",
            defaults={
                "service_type": Shipment.ServiceType.SURFACE,
                "weight_kg": Decimal("18.50"),
                "origin_city": "Delhi",
                "destination_city": "Mumbai",
                "sender_name": "Tech Distributors",
                "sender_phone": "9811998877",
                "receiver_name": "Vansh Soni",
                "receiver_phone": "6367743066",
                "status": Shipment.Status.IN_TRANSIT,
                "current_location": "Delhi Central Sort Hub",
                "estimated_delivery": now + timedelta(days=2),
            }
        )
        if created_s2 or not ship_2.events.exists():
            ShipmentEvent.objects.create(shipment=ship_2, status="Pickup Done", location="Delhi Okhla Hub", occurred_at=now - timedelta(days=2), remarks="Commercial heavy cargo collected.")
            ShipmentEvent.objects.create(shipment=ship_2, status="In Transit", location="Delhi Central Sort Hub", occurred_at=now - timedelta(days=1, hours=12), remarks="Inward weighing and dimension verification complete.")
            ShipmentEvent.objects.create(shipment=ship_2, status="In Transit", location="Delhi Sort Facility", occurred_at=now - timedelta(days=1), remarks="Staged for long-haul trailer dispatch.")
            ShipmentEvent.objects.create(shipment=ship_2, status="Delayed", location="Delhi Sort Hub", occurred_at=now - timedelta(hours=14), remarks="Delayed at Delhi Sort Hub due to road closure on NH-48. Staged for departure.")

        # Consignment 152785863851742 (Air Express - Out for Delivery Today)
        ship_3, created_s3 = Shipment.objects.get_or_create(
            workspace=workspace,
            awb="152785863851742",
            defaults={
                "service_type": Shipment.ServiceType.AIR_EXPRESS,
                "weight_kg": Decimal("0.30"),
                "origin_city": "Bangalore",
                "destination_city": "Jaipur",
                "sender_name": "HDFC Bank Cards",
                "sender_phone": "9880011223",
                "receiver_name": "Vansh Soni",
                "receiver_phone": "6367743066",
                "status": Shipment.Status.OUT_FOR_DELIVERY,
                "current_location": "Jaipur Delivery Center",
                "estimated_delivery": now,
            }
        )
        if created_s3 or not ship_3.events.exists():
            ShipmentEvent.objects.create(shipment=ship_3, status="Pickup Done", location="Bangalore Air Hub", occurred_at=now - timedelta(days=1), remarks="Handed over to Air Cargo dispatch.")
            ShipmentEvent.objects.create(shipment=ship_3, status="In Transit", location="Jaipur Airport Cargo Terminal", occurred_at=now - timedelta(hours=18), remarks="Flight arrived and deplaned.")
            ShipmentEvent.objects.create(shipment=ship_3, status="Reached at Destination", location="Jaipur Central Hub", occurred_at=now - timedelta(hours=10), remarks="Inward sorted at local distribution facility.")
            ShipmentEvent.objects.create(shipment=ship_3, status="In Transit", location="Jaipur Mansarovar Hub", occurred_at=now - timedelta(hours=4), remarks="Assigned to local delivery run.")
            ShipmentEvent.objects.create(shipment=ship_3, status="Out for Delivery", location="Jaipur Delivery Center", occurred_at=now - timedelta(hours=2), remarks="Out for delivery with delivery agent Rajesh (+91 98765 43210).")

        # Customer B: Riya Sharma Consignments
        ship_b1, _ = Shipment.objects.get_or_create(
            workspace=workspace,
            awb="152785863852001",
            defaults={
                "service_type": Shipment.ServiceType.SURFACE,
                "weight_kg": Decimal("2.10"),
                "origin_city": "Pune",
                "destination_city": "Jaipur",
                "sender_name": "Lifestyle Retail",
                "sender_phone": "9765432100",
                "receiver_name": "Riya Sharma",
                "receiver_phone": "9571538144",
                "status": Shipment.Status.DELIVERED,
                "delivered_at": now - timedelta(days=4),
            }
        )
        if not ship_b1.events.exists():
            ShipmentEvent.objects.create(shipment=ship_b1, status="Delivered", location="Jaipur Recipient Address", occurred_at=now - timedelta(days=4), remarks="Delivered to recipient.")

        ship_b2, _ = Shipment.objects.get_or_create(
            workspace=workspace,
            awb="152785863852002",
            defaults={
                "service_type": Shipment.ServiceType.SURFACE,
                "weight_kg": Decimal("0.80"),
                "origin_city": "Jaipur",
                "destination_city": "Hyderabad",
                "sender_name": "Riya Sharma",
                "sender_phone": "9571538144",
                "receiver_name": "Kavita Reddy",
                "receiver_phone": "9848011223",
                "status": Shipment.Status.PICKUP_SCHEDULED,
                "estimated_delivery": now + timedelta(days=4),
            }
        )
        if not ship_b2.events.exists():
            ShipmentEvent.objects.create(shipment=ship_b2, status="Pickup Scheduled", location="Jaipur Malviya Nagar", occurred_at=now - timedelta(hours=3), remarks="Doorstep collection scheduled between 2:00 PM and 6:00 PM.")

        ship_b3, _ = Shipment.objects.get_or_create(
            workspace=workspace,
            awb="152785863852003",
            defaults={
                "service_type": Shipment.ServiceType.SURFACE,
                "weight_kg": Decimal("3.50"),
                "origin_city": "Ahmedabad",
                "destination_city": "Jaipur",
                "sender_name": "Crafts of Gujarat",
                "sender_phone": "9925011223",
                "receiver_name": "Riya Sharma",
                "receiver_phone": "9571538144",
                "status": Shipment.Status.DELAYED,
                "current_location": "Jaipur Central Hub",
                "estimated_delivery": now + timedelta(days=1),
            }
        )
        if not ship_b3.events.exists():
            ShipmentEvent.objects.create(shipment=ship_b3, status="Delayed", location="Jaipur Central Hub", occurred_at=now - timedelta(hours=5), remarks="Address verification needed; house number missing in shipping label.")

        # 3 Weeks of Historical Analytics Tickets
        self._seed_historical_tickets(workspace, [team_tracking, team_claims], agent_user, now, prefix="EB")

    # -------------------------------------------------------------------------
    # 3 Weeks of Historical Analytics Tickets
    # -------------------------------------------------------------------------

    def _seed_historical_tickets(self, workspace, teams, agent_user, now, prefix="TK"):
        categories = ["Shipping & Logistics", "Returns & Exchanges", "Billing & Payments", "Technical Support", "General Support"]
        sentiments = ["POSITIVE", "NEUTRAL", "FRUSTRATED", "ANGRY"]

        historical_data = [
            ("Delayed Consignment Investigation", "Package delayed at central sort hub.", 20, Ticket.Priority.HIGH, Ticket.Status.RESOLVED, 0),
            ("Address Correction Request", "Customer provided corrected apartment number.", 18, Ticket.Priority.MEDIUM, Ticket.Status.RESOLVED, 1),
            ("Double Charge Billing Inquiry", "Customer reported duplicate debit hold on credit card.", 16, Ticket.Priority.CRITICAL, Ticket.Status.CLOSED, 0),
            ("Return Policy Clarification", "Inquiry regarding electronics return window.", 14, Ticket.Priority.LOW, Ticket.Status.RESOLVED, 1),
            ("Doorstep Pickup Reschedule", "Pickup requested for evening slot.", 12, Ticket.Priority.LOW, Ticket.Status.RESOLVED, 0),
            ("Damaged Outer Box Claim", "Outer cardboard carton crushed during transit.", 10, Ticket.Priority.HIGH, Ticket.Status.IN_PROGRESS, 1),
            ("Invoice & GST Receipt Request", "Customer requested business GST tax invoice.", 8, Ticket.Priority.LOW, Ticket.Status.RESOLVED, 0),
            ("Lost Package Trace Request", "Consignment not scanned for 48 hours.", 6, Ticket.Priority.CRITICAL, Ticket.Status.OPEN, 1),
            ("Cancellation Fee Inquiry", "Clarification on cancellation charges before dispatch.", 4, Ticket.Priority.LOW, Ticket.Status.RESOLVED, 0),
            ("Order Status Follow-up", "Follow-up regarding out-for-delivery package.", 2, Ticket.Priority.MEDIUM, Ticket.Status.CLOSED, 1),
        ]

        for i, (subj, desc, days_ago, prio, stat, team_idx) in enumerate(historical_data, start=100):
            ticket_num = f"{prefix}-{i}"
            created_dt = now - timedelta(days=days_ago)
            cust_name = f"Demo User {i}"
            cust_phone = f"987654{i:04d}"

            cust, _ = Customer.objects.get_or_create(
                workspace=workspace,
                normalized_phone=cust_phone,
                defaults={"name": cust_name, "email": f"user{i}@example.com", "phone": cust_phone}
            )

            conv, _ = Conversation.objects.get_or_create(
                workspace=workspace,
                customer=cust,
                channel=Conversation.Channel.WEB_CHAT,
                created_at=created_dt,
                defaults={
                    "status": Conversation.Status.COMPLETED,
                    "sentiment": sentiments[i % len(sentiments)],
                    "intent": "SUPPORT",
                    "urgency": prio,
                }
            )

            team = teams[team_idx % len(teams)]
            t, t_created = Ticket.objects.get_or_create(
                workspace=workspace,
                ticket_number=ticket_num,
                defaults={
                    "customer": cust,
                    "conversation": conv,
                    "subject": subj,
                    "description": desc,
                    "priority": prio,
                    "category": categories[i % len(categories)],
                    "status": stat,
                    "assigned_team": team,
                    "assigned_agent": agent_user,
                    "created_at": created_dt,
                    "updated_at": created_dt + timedelta(hours=2),
                }
            )
            if t_created:
                TicketEvent.objects.create(ticket=t, event_type="CREATED", description=f"Ticket #{ticket_num} created.", created_at=created_dt)
                if stat in [Ticket.Status.RESOLVED, Ticket.Status.CLOSED]:
                    TicketEvent.objects.create(ticket=t, event_type="RESOLVED", description=f"Resolved by agent {agent_user.email}.", created_at=created_dt + timedelta(hours=3))

    # -------------------------------------------------------------------------
    # Optional TechNova & FreshMart Seeding
    # -------------------------------------------------------------------------

    def _seed_technova_and_freshmart(self, now):
        # TechNova
        tn, _ = Workspace.objects.get_or_create(
            slug="technova",
            defaults={"name": "TechNova", "public_key": FIXED_WORKSPACE_KEYS["technova"], "status": Workspace.Status.ACTIVE}
        )
        WorkspaceSettings.objects.get_or_create(
            workspace=tn,
            defaults={"welcome_message": "Welcome to TechNova Developer Support!"}
        )
        self.stdout.write("  [+] TechNova workspace seeded.")

        # FreshMart
        fm, _ = Workspace.objects.get_or_create(
            slug="freshmart",
            defaults={"name": "FreshMart", "public_key": FIXED_WORKSPACE_KEYS["freshmart"], "status": Workspace.Status.ACTIVE}
        )
        WorkspaceSettings.objects.get_or_create(
            workspace=fm,
            defaults={"welcome_message": "Welcome to FreshMart 15-Minute Delivery Support!"}
        )
        self.stdout.write("  [+] FreshMart workspace seeded.")

    # -------------------------------------------------------------------------
    # Summary Table Output
    # -------------------------------------------------------------------------

    def _print_summary(self, seed_all=False):
        summary = f"""
========================================================================================
                      SUPPORTO AI DEMO SEEDING COMPLETE
========================================================================================

[1] PLATFORM ADMIN LOGIN:
    • URL:      http://127.0.0.1:8000/admin/
    • Email:    admin@admin.com
    • Password: admin
    • Role:     Superuser, Django Staff, Platform Admin

[2] WORKSPACE STAFF LOGINS:
    • ShopEase (E-commerce):
        - Owner:  owner@shopease.com    / ShopEase@123
        - Agent:  agent@shopease.com    / Agent@123
        - Portal: http://127.0.0.1:8000/shopease/dashboard/
    • ExpressBeas (Logistics):
        - Owner:  owner@expressbeas.in  / ExpressBeas@123
        - Agent:  agent@expressbeas.in  / Agent@123
        - Portal: http://127.0.0.1:8000/expressbeas/dashboard/

[3] CUSTOMER WIDGET & DEMO STOREFRONTS:
    • ShopEase Storefront:   http://127.0.0.1:8000/shopease/demo/
    • ExpressBeas Tracking:  http://127.0.0.1:8000/expressbeas/demo/

[4] VERIFIED DEMO PERSONAS:
    • Customer A: Vansh Soni  — Mobile: 6367743066  (Jaipur)
    • Customer B: Riya Sharma — Mobile: 9571538144  (Jaipur)

[5] 6 SAMPLE HACKATHON VERIFICATION QUERIES:
    1. "What are my orders?"                                [ShopEase / ExpressBeas]
    2. "Where is order SE-84920?"                           [ShopEase — Delivered, Return Scheduled]
    3. "Where is my consignment 152785863851740?"           [ExpressBeas — 6-event verified timeline]
    4. "What is the status of my return and refund?"        [ShopEase — Pickup Scheduled, INR 4,999]
    5. "Cancel order SE-84922"                              [ShopEase — Auto-Ticket, Real Ticket #]
    6. "Where is my consignment 152785863851740?" (with phone 9571538144) -> Access Denied (Safe Zero-Leak)

========================================================================================
"""
        self.stdout.write(summary)
