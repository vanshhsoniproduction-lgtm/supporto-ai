"""
seed_demo.py - Multi-tenant demo seeder for Supporto AI.
Seeds 4 realistic client workspaces:
  1. ExpressBeas (Courier & Logistics)
  2. ShopEase (Electronics E-commerce)
  3. TechNova (SaaS Platform)
  4. FreshMart (Hyperlocal Grocery Delivery)

Owner for all workspaces: vanshhsoni.production@gmail.com
Deterministic Public UUIDs guaranteed across database wipes.
"""
import uuid
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
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
from apps.emails.services.email_triage import email_triage_service

User = get_user_model()

OWNER_EMAILS = [
    "vanshhsoni.production@gmail.com",
    "sonivanshmaster@gmail.com",
    "vanshhsoni@gmail.com",
]

# Fixed Deterministic Public UUIDs
FIXED_WORKSPACE_KEYS = {
    "shopease": uuid.UUID("205efaa9-4d66-4903-b6f6-cccb701c8668"),
    "expressbeas": uuid.UUID("4ecc8df2-e72a-49e5-bb37-bb0211a39a05"),
    "technova": uuid.UUID("c10541fd-b19b-4aa5-98b6-1fcdbbeab550"),
    "freshmart": uuid.UUID("7f439472-80e5-4058-ab91-d884855ef2a5"),
}


class Command(BaseCommand):
    help = "Seeds professional demo data: ExpressBeas, ShopEase, TechNova, FreshMart."

    def handle(self, *args, **options):
        self.stdout.write("\n[*] Seeding Supporto AI multi-tenant demo data...\n")

        # ── 0. Platform Admin ────────────────────────────────────────────────
        admin_user, _ = User.objects.get_or_create(
            email="admin@supporto.ai",
            defaults={
                "username": "admin@supporto.ai",
                "first_name": "Platform",
                "last_name": "Admin",
                "is_staff": True,
                "is_superuser": True,
                "platform_role": User.PlatformRole.PLATFORM_ADMIN,
            }
        )
        admin_user.set_password("Supporto@Admin123")
        admin_user.is_staff = True
        admin_user.is_superuser = True
        admin_user.platform_role = User.PlatformRole.PLATFORM_ADMIN
        admin_user.save()
        self.stdout.write("  [+] Platform admin ready (admin@supporto.ai)")

        # ── 1. Workspace Configurations ──────────────────────────────────────
        workspaces_config = [
            {
                "slug": "expressbeas",
                "name": "ExpressBeas",
                "description": "Fast and reliable nationwide courier and supply-chain logistics. Real-time AWB tracking, express delivery, and last-mile fulfillment.",
                "website": "https://expressbeas.in",
                "support_email": "vanshhsoni.production@gmail.com",
                "welcome_message": "Welcome to ExpressBeas Support! Track your shipment AWB, report a delayed parcel, or schedule a pickup. How can we help today?",
                "sla_urgent": 10,
                "sla_standard": 8,
                "orders_webhook": "http://127.0.0.1:8000/api/v1/mock-store/lookup/",
                "orders_secret": "sk_expressbeas_live_awb_2026",
                "webhooks": [
                    {
                        "name": "ExpressBeas Public AWB Tracking API",
                        "type": WorkspaceWebhook.WebhookType.TRACKING,
                        "url": "http://127.0.0.1:8000/api/v1/mock-store/lookup/",
                        "secret": "sk_expressbeas_live_awb_2026"
                    },
                    {
                        "name": "Delhivery Partner Fleet API",
                        "type": WorkspaceWebhook.WebhookType.TRACKING,
                        "url": "https://dlv-api.delhivery.com/api/v1/packages/json",
                        "secret": "delhivery_api_token_live"
                    }
                ],
                "system_prompt": (
                    "You are Supporto AI for ExpressBeas Logistics. "
                    "Help customers track Air Waybill (AWB) consignment numbers (e.g. EB987654321, EB123456789), "
                    "schedule pickups, report damaged or missing parcels, and understand delivery timelines. "
                    "For lost packages or damaged consignments, immediately escalate to Claims & Disputes. "
                    "Keep answers concise, actionable, and accurate."
                ),
                "mailbox_email": "support@expressbeas.in",
                "teams": [
                    {"slug": "tracking-delivery", "name": "Tracking & Delivery", "desc": "Handles live AWB tracking, delivery delay investigations, and last-mile rider coordination."},
                    {"slug": "claims-disputes", "name": "Claims & Disputes", "desc": "Handles lost parcels, damaged consignments, compensation claims, and vendor disputes."},
                ],
                "staff": [
                    ("priya.sharma@expressbeas.in", "Priya", "Sharma", "AGENT", ["tracking-delivery"]),
                    ("rahul.mehta@expressbeas.in", "Rahul", "Mehta", "AGENT", ["tracking-delivery", "claims-disputes"]),
                    ("anjali.singh@expressbeas.in", "Anjali", "Singh", "MANAGER", ["tracking-delivery", "claims-disputes"]),
                ],
                "faqs": [
                    (
                        "AWB Tracking & Status Scans",
                        "How do I track my ExpressBeas shipment with AWB number?",
                        "Enter your 11-digit AWB number (starts with EB, like EB987654321) in the chat or visit expressbeas.in/track. Scans are recorded at each sort facility: Booked -> Hub Inward -> In Transit -> Out for Delivery -> Delivered."
                    ),
                    (
                        "Delivery Timelines & Express Slots",
                        "How long does delivery take for standard and express shipments?",
                        "Same-city deliveries take 24 hours. Metro-to-metro surface shipments arrive in 2-3 business days. Air Express arrives within 24-48 hours. Remote locations take 4-6 business days."
                    ),
                    (
                        "Lost or Damaged Parcel Claim",
                        "What is the claim process for lost or damaged goods?",
                        "Claims must be lodged within 7 days of scheduled delivery. Provide your AWB number and damage photos. Our Claims team investigates within 48 business hours, and refunds or insurance settlements are credited within 5-7 business days."
                    ),
                    (
                        "Schedule a Doorstep Pickup",
                        "Can I schedule a doorstep pickup for my package?",
                        "Yes. Pickups scheduled before 12:00 PM are completed the same day between 2:00 PM and 6:00 PM. Our dispatch rider will weigh the package and provide your official AWB receipt upon collection."
                    ),
                ],
                "sample_emails": [
                    (
                        "eb_msg_001",
                        "rohit.kumar@example.com",
                        "Rohit Kumar",
                        "Urgent: Consignment EB987654321 delayed at Delhi hub for 5 days",
                        "Hello, my shipment with AWB EB987654321 contains urgent medical supplies. Tracking shows it stuck at Delhi Sort Hub since Oct 26. Please escalate immediately to rider dispatch.",
                        "CRITICAL",
                        "SHIPPING",
                        "tracking-delivery",
                    ),
                    (
                        "eb_msg_002",
                        "meera.patel@example.com",
                        "Meera Patel",
                        "Damage claim for crushed package EB112233445",
                        "The delivery arrived yesterday with outer carton crushed. The internal electronic tablet is broken. I want to file a formal damage compensation claim under invoice #INV-9921.",
                        "HIGH",
                        "RETURNS",
                        "claims-disputes",
                    ),
                    (
                        "eb_msg_003",
                        "arjun.nair@example.com",
                        "Arjun Nair",
                        "Pickup inquiry for 25 bulk cartons from Pune warehouse",
                        "We need to schedule a truck pickup tomorrow for 25 commercial parcels from our Pune industrial unit to Bangalore. Please confirm rates and vehicle assignment.",
                        "LOW",
                        "GENERAL",
                        "tracking-delivery",
                    ),
                ],
                "customers": [
                    ("Rohit Kumar", "rohit.kumar@example.com", "WIDGET", "WEB_CHAT",
                     "Delayed AWB EB987654321", "FRUSTRATED", "CRITICAL",
                     "Consignment EB987654321 delayed at Delhi hub for 5 days without updates.",
                     "EB-TK-101", "Delayed Consignment EB987654321 at Delhi Hub", "Logistics & Delivery",
                     "CRITICAL", "IN_PROGRESS", "tracking-delivery", "rahul.mehta@expressbeas.in", 1, None),
                    ("Meera Patel", "meera.patel@example.com", "EMAIL", "EMAIL",
                     "Damage Claim EB112233445", "ANGRY", "HIGH",
                     "Package delivered with outer carton crushed; internal tablet screen shattered.",
                     "EB-TK-102", "Damage Claim for Crushed Package EB112233445", "Claims & Disputes",
                     "HIGH", "OPEN", "claims-disputes", "anjali.singh@expressbeas.in", 2, None),
                    ("Sameer Sen", "sameer.sen@example.com", "WIDGET", "WEB_CHAT",
                     "Failed Delivery Attempt", "FRUSTRATED", "MEDIUM",
                     "Rider marked customer unavailable although I was home all afternoon waiting.",
                     "EB-TK-103", "False Delivery Attempt - Customer Was Home", "Logistics & Delivery",
                     "MEDIUM", "RESOLVED", "tracking-delivery", "priya.sharma@expressbeas.in", 3, 3.8),
                    ("Kavita Reddy", "kavita.reddy@example.com", "WIDGET", "WEB_CHAT",
                     "Address Correction", "NEUTRAL", "HIGH",
                     "Requested urgent flat number correction for out-for-delivery parcel EB123456789.",
                     "EB-TK-104", "Urgent Address Correction for AWB EB123456789", "Logistics & Delivery",
                     "HIGH", "RESOLVED", "tracking-delivery", "rahul.mehta@expressbeas.in", 4, 1.5),
                    ("Vikram Malhotra", "vikram.m@example.com", "EMAIL", "EMAIL",
                     "Lost Commercial Cargo", "ANGRY", "CRITICAL",
                     "Commercial parcel missing for 12 days between Jaipur hub and Ahmedabad.",
                     "EB-TK-105", "Lost Shipment Investigation for Commercial Cargo", "Claims & Disputes",
                     "CRITICAL", "IN_PROGRESS", "claims-disputes", "anjali.singh@expressbeas.in", 5, None),
                    ("Anita Rao", "anita.rao@example.com", "WIDGET", "WEB_CHAT",
                     "Pickup Reschedule", "NEUTRAL", "LOW",
                     "Client requested rescheduling warehouse parcel pickup from morning to 4 PM.",
                     "EB-TK-106", "Pickup Reschedule Request for Bangalore Unit", "Logistics & Delivery",
                     "LOW", "RESOLVED", "tracking-delivery", "priya.sharma@expressbeas.in", 6, 2.2),
                    ("Siddharth Joshi", "siddharth.j@example.com", "WIDGET", "WEB_CHAT",
                     "Missing Scan Status", "FRUSTRATED", "MEDIUM",
                     "Tracking status not updated since parcel departed Mumbai Airport 48h ago.",
                     "EB-TK-107", "Missing Inward Scan After Mumbai Airport Departure", "Logistics & Delivery",
                     "MEDIUM", "OPEN", "tracking-delivery", "rahul.mehta@expressbeas.in", 7, None),
                ]
            },
            {
                "slug": "shopease",
                "name": "ShopEase",
                "description": "Premier modern e-commerce storefront specializing in smart electronics, home devices, and audio accessories.",
                "website": "https://shopease.example.com",
                "support_email": "vanshhsoni.production@gmail.com",
                "welcome_message": "Welcome to ShopEase Support! How can our AI assistant help you with your order, returns, or billing today?",
                "sla_urgent": 15,
                "sla_standard": 12,
                "orders_webhook": "http://127.0.0.1:8000/api/v1/mock-store/lookup/",
                "orders_secret": "sk_shopease_demo_secret_2026",
                "webhooks": [
                    {
                        "name": "Shopify Store Orders API",
                        "type": WorkspaceWebhook.WebhookType.ORDERS,
                        "url": "http://127.0.0.1:8000/api/v1/mock-store/lookup/",
                        "secret": "sk_shopease_demo_secret_2026"
                    }
                ],
                "system_prompt": (
                    "You are Supporto AI for ShopEase. Empathize with the customer, keep responses concise, "
                    "and refer strictly to ShopEase policies. For double charges, immediately escalate to Billing Support."
                ),
                "mailbox_email": "support@shopease.com",
                "teams": [
                    {"slug": "order-support", "name": "Order Support", "desc": "Handles shipments, fulfillment, order status, and delivery issues."},
                    {"slug": "billing-support", "name": "Billing Support", "desc": "Handles payment discrepancies, refunds, duplicate charges, and invoices."},
                    {"slug": "technical-support", "name": "Technical Support", "desc": "Handles app crashes, website login issues, software bugs, and device integration."},
                ],
                "staff": [
                    ("sarah.connor@shopease.com", "Sarah", "Connor", "AGENT", ["order-support", "technical-support"]),
                    ("marcus.wright@shopease.com", "Marcus", "Wright", "AGENT", ["order-support", "billing-support", "technical-support"]),
                    ("kyle.reese@shopease.com", "Kyle", "Reese", "AGENT", ["billing-support"]),
                    ("john.connor@shopease.com", "John", "Connor", "MANAGER", ["order-support", "billing-support", "technical-support"]),
                ],
                "faqs": [
                    ("Return & Exchange Policy",
                     "What is ShopEase's return and exchange policy?",
                     "We offer a 30-day hassle-free return window on all electronics and accessories in their original packaging. Return shipping is completely free for damaged or defective items."),
                    ("Standard Shipping Timelines",
                     "How long does delivery take for standard orders?",
                     "Standard domestic shipping takes 3 to 5 business days. Express 2-day delivery is available at checkout. Tracking information is sent via email once your package departs our warehouse."),
                    ("Duplicate Charge & Billing Resolution",
                     "What should I do if my credit card was charged twice?",
                     "If you see a duplicate pending authorization on your bank statement, please notify our Billing Support team with your order number. Our automated verification releases secondary holds within 2-4 business hours."),
                    ("Canceling or Modifying an Order",
                     "Can I cancel or change my shipping address after placing an order?",
                     "Orders can be canceled or updated within 1 hour of placement before warehouse dispatch by contacting support with your order number."),
                ],
                "sample_emails": [
                    ("se_msg_001", "alex.rivera@example.com", "Alex Rivera",
                     "Double charge on my credit card for Order #SE-99124",
                     "Hello Support, I noticed my bank account was charged twice for $149.99 on Order #SE-99124. This is an unauthorized duplicate charge. Please refund the duplicate immediately as this is urgent.",
                     "CRITICAL", "BILLING", "billing-support"),
                    ("se_msg_002", "jordan.lee@example.com", "Jordan Lee",
                     "Order status inquiry for package #SE-88210",
                     "Hi there, I placed an order three days ago for smart wireless headphones. Can you please check when it is scheduled to arrive at my address?",
                     "LOW", "SHIPPING", "order-support"),
                ],
                "customers": [
                    ("Elena Fisher", "elena.fisher@example.com", "WIDGET", "WEB_CHAT",
                     "Duplicate Payment Discrepancy", "FRUSTRATED", "CRITICAL",
                     "My credit card was charged twice ($199) for order SE-84920! Cancel it and refund my money immediately!",
                     "TK-84920", "Double Charge on Order #SE-84920 ($199)", "Billing & Payments",
                     "CRITICAL", "IN_PROGRESS", "billing-support", "marcus.wright@shopease.com", 1, None),
                    ("David Miller", "david.m@example.com", "EMAIL", "EMAIL",
                     "Shipping Delay Inquiry", "NEUTRAL", "MEDIUM",
                     "Order SE-88210 smart wireless headphones delayed beyond estimated delivery date.",
                     "TK-88210", "Delayed Shipment for Order #SE-88210", "Order & Shipping",
                     "MEDIUM", "OPEN", "order-support", "sarah.connor@shopease.com", 2, None),
                    ("Claire Redfield", "claire.r@example.com", "WIDGET", "WEB_CHAT",
                     "Damaged Item on Delivery", "ANGRY", "HIGH",
                     "Screen cracked on arrival for 4K Ultra HD Monitor; protective seal was broken.",
                     "TK-89101", "Damaged Item - Cracked Screen on Ultra HD Monitor", "Damaged & Defective",
                     "HIGH", "OPEN", "order-support", "sarah.connor@shopease.com", 3, None),
                    ("Nathan Drake", "nathan.d@example.com", "WIDGET", "WEB_CHAT",
                     "Return Window Question", "POSITIVE", "LOW",
                     "Customer inquired about 30-day return policy for unopened noise-canceling headphones.",
                     "TK-89102", "Return Policy Inquiry for Audio Headphones", "Returns & Exchanges",
                     "LOW", "RESOLVED", "order-support", "john.connor@shopease.com", 4, 2.4),
                    ("Leon Kennedy", "leon.k@example.com", "EMAIL", "EMAIL",
                     "Checkout Payment Error", "FRUSTRATED", "HIGH",
                     "Bank deducted amount during checkout timeout but order confirmation was not generated.",
                     "TK-89103", "Gateway Timeout During Order Placement", "Billing & Payments",
                     "HIGH", "RESOLVED", "billing-support", "kyle.reese@shopease.com", 5, 2.1),
                    ("Jill Valentine", "jill.v@example.com", "WIDGET", "WEB_CHAT",
                     "Shipping Address Update", "NEUTRAL", "MEDIUM",
                     "Customer submitted apartment number change within 30 minutes of placing order SE-90112.",
                     "TK-89104", "Delivery Address Modification Pre-Dispatch", "Order & Shipping",
                     "MEDIUM", "RESOLVED", "order-support", "sarah.connor@shopease.com", 6, 1.2),
                    ("Sam Fisher", "sam.fisher@example.com", "EMAIL", "EMAIL",
                     "Defective Cable Replacement", "NEUTRAL", "MEDIUM",
                     "Braided USB-C fast charging cable stopped working after 3 days of light use.",
                     "TK-89105", "Defective USB-C Braided Cable Replacement", "Damaged & Defective",
                     "MEDIUM", "RESOLVED", "order-support", "john.connor@shopease.com", 7, 3.5),
                    ("Chloe Frazer", "chloe.f@example.com", "WIDGET", "WEB_CHAT",
                     "Where is My Order", "NEUTRAL", "LOW",
                     "Where is my order SE-84920? Requested current transit tracking status.",
                     "TK-89106", "Order Tracking Verification for SE-84920", "Order & Shipping",
                     "LOW", "RESOLVED", "order-support", "marcus.wright@shopease.com", 8, 0.8),
                ]
            }
        ]

        # ── 2. Seed Each Workspace ───────────────────────────────────────────
        all_outputs = []

        for ws_data in workspaces_config:
            slug = ws_data["slug"]
            self.stdout.write(f"\n  -> Setting up workspace: {ws_data['name']} (/{slug}/)")

            # Create or update Workspace with deterministic public_key
            workspace, _ = Workspace.objects.get_or_create(
                slug=slug,
                defaults={
                    "name": ws_data["name"],
                    "description": ws_data["description"],
                    "status": Workspace.Status.ACTIVE,
                }
            )
            workspace.name = ws_data["name"]
            workspace.description = ws_data["description"]
            workspace.status = Workspace.Status.ACTIVE
            if slug in FIXED_WORKSPACE_KEYS:
                workspace.public_key = FIXED_WORKSPACE_KEYS[slug]
            workspace.save()

            # Settings
            ws_settings, _ = WorkspaceSettings.objects.get_or_create(
                workspace=workspace,
                defaults={
                    "company_website": ws_data["website"],
                    "support_email": ws_data["support_email"],
                    "welcome_message": ws_data["welcome_message"],
                    "sla_urgent_minutes": ws_data["sla_urgent"],
                    "sla_standard_hours": ws_data["sla_standard"],
                    "ticket_auto_assignment": True,
                    "orders_api_webhook_url": ws_data["orders_webhook"],
                    "orders_api_secret_key": ws_data["orders_secret"],
                    "customer_verification_secret": f"hmac_secret_{slug}_2026",
                }
            )
            ws_settings.company_website = ws_data["website"]
            ws_settings.support_email = ws_data["support_email"]
            ws_settings.welcome_message = ws_data["welcome_message"]
            ws_settings.orders_api_webhook_url = ws_data["orders_webhook"]
            ws_settings.orders_api_secret_key = ws_data["orders_secret"]
            ws_settings.customer_verification_secret = f"hmac_secret_{slug}_2026"
            ws_settings.save()

            # Seed Webhooks
            for wh_info in ws_data.get("webhooks", []):
                WorkspaceWebhook.objects.get_or_create(
                    workspace=workspace,
                    url=wh_info["url"],
                    defaults={
                        "name": wh_info["name"],
                        "webhook_type": wh_info["type"],
                        "secret_key": wh_info["secret"],
                        "is_active": True,
                    }
                )

            # Pre-Authorize Owners (vanshhsoni.production@gmail.com, etc.)
            for dev_email in OWNER_EMAILS:
                dev_user, _ = User.objects.get_or_create(
                    email=dev_email,
                    defaults={"first_name": "Vansh", "last_name": "Soni", "username": dev_email}
                )
                WorkspaceMembership.objects.update_or_create(
                    workspace=workspace,
                    user=dev_user,
                    defaults={"role": WorkspaceMembership.Role.OWNER, "is_active": True}
                )
                WorkspaceAuthorizedEmail.objects.update_or_create(
                    workspace=workspace,
                    normalized_email=dev_email,
                    defaults={
                        "email": dev_email,
                        "assigned_role": WorkspaceMembership.Role.OWNER,
                        "status": WorkspaceAuthorizedEmail.Status.AUTHORIZED,
                        "linked_user": dev_user,
                        "invited_by": admin_user,
                    }
                )

            # Seed Teams
            teams_map = {}
            for t_info in ws_data["teams"]:
                team, _ = Team.objects.get_or_create(
                    workspace=workspace,
                    slug=t_info["slug"],
                    defaults={"name": t_info["name"], "description": t_info["desc"], "is_active": True}
                )
                team.name = t_info["name"]
                team.description = t_info["desc"]
                team.is_active = True
                team.save()
                teams_map[t_info["slug"]] = team

            # Seed Staff Users
            staff_users = {}
            for email, fn, ln, role_str, team_slugs in ws_data["staff"]:
                staff_u, _ = User.objects.get_or_create(
                    email=email,
                    defaults={"first_name": fn, "last_name": ln, "username": email}
                )
                staff_u.set_password("Support@Demo123")
                staff_u.save()

                role = getattr(WorkspaceMembership.Role, role_str, WorkspaceMembership.Role.AGENT)
                WorkspaceMembership.objects.update_or_create(
                    workspace=workspace,
                    user=staff_u,
                    defaults={"role": role, "is_active": True}
                )

                assigned_teams = [teams_map[ts] for ts in team_slugs if ts in teams_map]
                auth_rec, _ = WorkspaceAuthorizedEmail.objects.update_or_create(
                    workspace=workspace,
                    normalized_email=email,
                    defaults={
                        "email": email,
                        "assigned_role": role,
                        "status": WorkspaceAuthorizedEmail.Status.AUTHORIZED,
                        "linked_user": staff_u,
                        "invited_by": admin_user,
                    }
                )
                auth_rec.assigned_teams.set(assigned_teams)

                for team_obj in assigned_teams:
                    TeamMembership.objects.get_or_create(
                        team=team_obj,
                        user=staff_u,
                        defaults={"role": TeamMembership.Role.MEMBER}
                    )
                staff_users[email] = staff_u

            # Knowledge Base FAQs
            for title, q, a in ws_data["faqs"]:
                doc, _ = KnowledgeDocument.objects.get_or_create(
                    workspace=workspace,
                    title=title,
                    defaults={
                        "doc_type": KnowledgeDocument.DocType.FAQ,
                        "question": q,
                        "answer": a,
                        "content": f"Q: {q}\nA: {a}",
                        "is_active": True,
                    }
                )
                try:
                    document_processor.chunk_and_index(doc)
                except Exception:
                    pass

            # AI & Voice Configurations
            AgentConfiguration.objects.update_or_create(
                workspace=workspace,
                defaults={
                    "system_prompt": ws_data["system_prompt"],
                    "confidence_threshold": 0.75,
                    "auto_escalate_urgent": True,
                }
            )
            VoiceConfiguration.objects.get_or_create(
                workspace=workspace,
                defaults={"is_enabled": True, "voice_name": "af_sarah", "speed": 1.0}
            )

            # Mailbox Connection
            mailbox, _ = MailboxConnection.objects.get_or_create(
                workspace=workspace,
                email_address=ws_data["mailbox_email"],
                defaults={
                    "provider": MailboxConnection.Provider.GMAIL,
                    "status": MailboxConnection.Status.ACTIVE,
                    "provider_account_id": f"{slug}_support_inbox",
                    "last_successful_sync_at": timezone.now(),
                }
            )

            # Seed Sample Inbound Emails
            for p_id, s_email, s_name, subj, body, urg, intent, team_slug in ws_data["sample_emails"]:
                inbound_email, created = InboundEmail.objects.get_or_create(
                    workspace=workspace,
                    provider_message_id=p_id,
                    defaults={
                        "mailbox_connection": mailbox,
                        "sender_email": s_email,
                        "sender_name": s_name,
                        "recipient": ws_data["mailbox_email"],
                        "subject": subj,
                        "original_text_body": body,
                        "normalized_text_body": body,
                        "received_at": timezone.now(),
                        "processing_status": InboundEmail.ProcessingStatus.TICKET_PROPOSED,
                    }
                )
                if created:
                    try:
                        email_triage_service.process_inbound_email(inbound_email)
                    except Exception:
                        pass

            # Seed Customers & Historical Tickets
            first_team = list(teams_map.values())[0] if teams_map else None
            now = timezone.now()

            for item in ws_data["customers"]:
                (cust_name, cust_email, source, channel,
                 intent, sentiment, urgency, summary,
                 ticket_no, ticket_subj, ticket_cat, ticket_pri, ticket_status,
                 team_slug, agent_email, days_ago, res_hours) = item

                customer, _ = Customer.objects.get_or_create(
                    workspace=workspace,
                    normalized_email=cust_email,
                    defaults={
                        "name": cust_name,
                        "email": cust_email,
                        "is_anonymous": False,
                        "source": getattr(Customer.Source, source, Customer.Source.WIDGET),
                    }
                )

                created_time = now - timedelta(days=days_ago, hours=2)

                conv_status = Conversation.Status.ACTIVE if ticket_status != "RESOLVED" else Conversation.Status.COMPLETED
                conv_sentiment = getattr(Conversation.Sentiment, sentiment, None)
                if not conv_sentiment:
                    conv_sentiment = Conversation.Sentiment.FRUSTRATED if sentiment == "ANGRY" else Conversation.Sentiment.NEUTRAL

                assigned_team = teams_map.get(team_slug, first_team)
                assigned_agent = staff_users.get(agent_email)

                ticket = Ticket.objects.filter(workspace=workspace, ticket_number=ticket_no).first()
                if not ticket:
                    conv = Conversation.objects.create(
                        workspace=workspace,
                        customer=customer,
                        channel=getattr(Conversation.Channel, channel, Conversation.Channel.WEB_CHAT),
                        status=conv_status,
                        intent=intent,
                        sentiment=conv_sentiment,
                        urgency=getattr(Conversation.Urgency, urgency, Conversation.Urgency.MEDIUM),
                        summary=summary,
                    )
                    Conversation.objects.filter(id=conv.id).update(created_at=created_time)

                    ticket_defaults = {
                        "customer": customer,
                        "conversation": conv,
                        "subject": ticket_subj,
                        "description": summary,
                        "category": ticket_cat,
                        "priority": getattr(Ticket.Priority, ticket_pri, Ticket.Priority.MEDIUM),
                        "status": getattr(Ticket.Status, ticket_status, Ticket.Status.OPEN),
                        "assigned_team": assigned_team,
                    }
                    if assigned_agent:
                        ticket_defaults["assigned_agent"] = assigned_agent

                    ticket = Ticket.objects.create(
                        workspace=workspace,
                        ticket_number=ticket_no,
                        **ticket_defaults
                    )

                resolved_time = (created_time + timedelta(hours=res_hours)) if res_hours else None
                Ticket.objects.filter(id=ticket.id).update(
                    created_at=created_time,
                    resolved_at=resolved_time
                )

                resolved_time = (created_time + timedelta(hours=res_hours)) if res_hours else None
                Ticket.objects.filter(id=ticket.id).update(
                    created_at=created_time,
                    resolved_at=resolved_time
                )

                owner_user = User.objects.filter(email=OWNER_EMAILS[0]).first()
                if owner_user:
                    TicketAssignment.objects.get_or_create(
                        ticket=ticket,
                        assigned_by=owner_user,
                        defaults={
                            "new_team": assigned_team,
                            "new_agent": assigned_agent,
                            "reason": "AI Auto-Triage & Intent Routing"
                        }
                    )

            self.stdout.write(f"    [+] {ws_data['name']} workspace ready")
            all_outputs.append((ws_data["name"], workspace.slug, str(workspace.public_key)))

        # ── 3. Summary ───────────────────────────────────────────────────────
        self.stdout.write(self.style.SUCCESS("\n[+] Demo data successfully seeded for both enterprise clients (ExpressBeas & ShopEase)!\n"))
        self.stdout.write("    Platform Admin   : /admin/  (admin@supporto.ai / Supporto@Admin123)")
        self.stdout.write(f"    Owner Sign-In    : Sign in with Google as: {OWNER_EMAILS[0]}")
        self.stdout.write("    " + "-" * 60)
        for name, slug, pk in all_outputs:
            self.stdout.write(f"    {name:15s} Portal : /{slug}/")
            self.stdout.write(f"    {name:15s} Widget : /widget/{pk}/demo/\n")
