from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from apps.workspaces.models import Workspace, WorkspaceMembership, WorkspaceSettings
from apps.teams.models import Team, TeamMembership
from apps.customers.models import Customer
from apps.conversations.models import Conversation, Message
from apps.tickets.models import Ticket, TicketComment, TicketEvent
from apps.knowledge_base.models import KnowledgeDocument
from apps.ai_engine.models import AgentConfiguration
from apps.voice_support.models import VoiceConfiguration, IVRMenu, IVROption

User = get_user_model()

class Command(BaseCommand):
    help = "Seeds initial development demo data including ShopEase workspace, teams, staff, and tickets."

    def handle(self, *args, **options):
        self.stdout.write("[*] Seeding Supporto AI demo data...")

        # 1. Create Workspace
        workspace, created = Workspace.objects.get_or_create(
            slug="shopease",
            defaults={
                "name": "ShopEase",
                "description": "Premier modern e-commerce storefront specializing in smart electronics and accessories.",
                "status": Workspace.Status.ACTIVE,
            }
        )

        WorkspaceSettings.objects.get_or_create(
            workspace=workspace,
            defaults={
                "company_website": "https://shopease.example.com",
                "support_email": "support@shopease.example.com",
                "welcome_message": "Welcome to ShopEase Support! How can our AI assistant help you with your order, returns, or billing today?",
                "sla_urgent_minutes": 15,
                "sla_standard_hours": 12,
                "ticket_auto_assignment": True,
            }
        )

        # 2. Workspace Owner
        owner, _ = User.objects.get_or_create(
            email="owner@shopease.com",
            defaults={"first_name": "Elena", "last_name": "Vance", "username": "owner@shopease.com"}
        )
        owner.set_password("ShopEase@123")
        owner.save()

        WorkspaceMembership.objects.get_or_create(
            workspace=workspace,
            user=owner,
            defaults={"role": WorkspaceMembership.Role.OWNER, "is_active": True}
        )

        # 3. Staff Users
        staff_data = [
            ("agent.one@shopease.com", "Sarah", "Connor", WorkspaceMembership.Role.AGENT),
            ("agent.two@shopease.com", "Marcus", "Wright", WorkspaceMembership.Role.AGENT), # Multi-team agent!
            ("agent.three@shopease.com", "Kyle", "Reese", WorkspaceMembership.Role.AGENT),
            ("manager@shopease.com", "John", "Connor", WorkspaceMembership.Role.MANAGER),
        ]

        staff_users = {}
        for email, fn, ln, role in staff_data:
            u, _ = User.objects.get_or_create(
                email=email,
                defaults={"first_name": fn, "last_name": ln, "username": email}
            )
            u.set_password("ShopEase@123")
            u.save()
            WorkspaceMembership.objects.get_or_create(
                workspace=workspace,
                user=u,
                defaults={"role": role, "is_active": True}
            )
            staff_users[email] = u

        # 4. Teams: Order Support & Billing Support
        order_team, _ = Team.objects.get_or_create(
            workspace=workspace,
            slug="order-support",
            defaults={"name": "Order Support", "description": "Handles shipments, fulfillment, order status, and delivery issues."}
        )
        billing_team, _ = Team.objects.get_or_create(
            workspace=workspace,
            slug="billing-support",
            defaults={"name": "Billing Support", "description": "Handles payment discrepancies, refunds, duplicate charges, and invoices."}
        )

        # Order Support members
        TeamMembership.objects.get_or_create(team=order_team, user=staff_users["agent.one@shopease.com"], defaults={"role": TeamMembership.Role.MEMBER})
        TeamMembership.objects.get_or_create(team=order_team, user=staff_users["agent.two@shopease.com"], defaults={"role": TeamMembership.Role.LEAD})

        # Billing Support members (Marcus belongs to both teams!)
        TeamMembership.objects.get_or_create(team=billing_team, user=staff_users["agent.two@shopease.com"], defaults={"role": TeamMembership.Role.MEMBER})
        TeamMembership.objects.get_or_create(team=billing_team, user=staff_users["agent.three@shopease.com"], defaults={"role": TeamMembership.Role.LEAD})

        # 5. Knowledge Base FAQs
        faqs = [
            (
                "Return & Exchange Policy",
                "What is ShopEase's return and exchange policy?",
                "We offer a 30-day hassle-free return window on all electronics and accessories in their original packaging. Return shipping is completely free for damaged or defective items."
            ),
            (
                "Standard Shipping Timelines",
                "How long does delivery take for standard orders?",
                "Standard domestic shipping takes 3 to 5 business days. Express 2-day delivery is available at checkout. Tracking information is sent via email once your package departs our warehouse."
            ),
            (
                "Duplicate Charge & Billing Resolution",
                "What should I do if my credit card was charged twice?",
                "If you see a duplicate pending authorization on your bank statement, please notify our Billing Support team with your order number. Our automated verification releases secondary holds within 2-4 business hours."
            ),
            (
                "Canceling or Modifying an Order",
                "Can I cancel or change my shipping address after placing an order?",
                "Orders can be canceled or updated within 1 hour of placement before warehouse dispatch by contacting support with your order number."
            )
        ]
        for title, q, a in faqs:
            KnowledgeDocument.objects.get_or_create(
                workspace=workspace,
                title=title,
                defaults={
                    "doc_type": KnowledgeDocument.DocType.FAQ,
                    "question": q,
                    "answer": a,
                    "content": f"Q: {q}\nA: {a}",
                    "is_active": True
                }
            )

        # 6. AI & Voice Configurations
        AgentConfiguration.objects.get_or_create(
            workspace=workspace,
            defaults={
                "system_prompt": "You are Supporto AI for ShopEase. Empathize with the customer, keep responses concise, and refer strictly to ShopEase policies. For double charges, immediately escalate to Billing Support.",
                "confidence_threshold": 0.75,
                "auto_escalate_urgent": True,
            }
        )

        v_config, _ = VoiceConfiguration.objects.get_or_create(
            workspace=workspace,
            defaults={
                "is_enabled": True,
                "voice_name": "af_sarah",
                "speed": 1.0,
                "welcome_voice_text": "Thank you for contacting ShopEase support. How can I help you today?"
            }
        )

        # IVR Menu
        ivr_menu, _ = IVRMenu.objects.get_or_create(workspace=workspace, name="Main Support Menu")
        IVROption.objects.get_or_create(menu=ivr_menu, digit=1, defaults={"label": "Order Tracking & Delivery", "target_team": order_team})
        IVROption.objects.get_or_create(menu=ivr_menu, digit=2, defaults={"label": "Billing & Double Charges", "target_team": billing_team})
        IVROption.objects.get_or_create(menu=ivr_menu, digit=3, defaults={"label": "Speak with AI Assistant", "action_type": IVROption.ActionType.ROUTE_AI})

        # 7. Demo Customers & Conversations
        c1, _ = Customer.objects.get_or_create(
            workspace=workspace,
            email="alice.morgan@example.com",
            defaults={"name": "Alice Morgan", "is_anonymous": False, "session_token": "demo-sess-alice-1"}
        )
        c2, _ = Customer.objects.get_or_create(
            workspace=workspace,
            email="david.miller@example.com",
            defaults={"name": "David Miller", "is_anonymous": False, "session_token": "demo-sess-david-2"}
        )
        c3, _ = Customer.objects.get_or_create(
            workspace=workspace,
            name="Anonymous Buyer",
            defaults={"is_anonymous": True, "session_token": "demo-sess-anon-3"}
        )

        # Conversation 1: Critical Billing Issue
        conv1, _ = Conversation.objects.get_or_create(
            workspace=workspace,
            customer=c1,
            defaults={
                "channel": Conversation.Channel.WEB_CHAT,
                "status": Conversation.Status.COMPLETED,
                "intent": "Billing & Payments",
                "sentiment": Conversation.Sentiment.FRUSTRATED,
                "urgency": Conversation.Urgency.CRITICAL,
                "is_escalated": True,
                "summary": "Customer reports being charged twice for headphones (Order #SE-84920). Urgent billing escalation triggered."
            }
        )
        Message.objects.get_or_create(conversation=conv1, sender_type=Message.SenderType.CUSTOMER, content="Hi, my bank statement shows I was deducted twice for Order #SE-84920! Please help immediately.")
        Message.objects.get_or_create(conversation=conv1, sender_type=Message.SenderType.AI, content="I understand this is frustrating. I have flagged this as critical and escalated your case directly to our Billing Support team.")

        # Ticket 1 (Critical, Assigned to Billing Support)
        t1, _ = Ticket.objects.get_or_create(
            workspace=workspace,
            ticket_number="TK-260101",
            defaults={
                "customer": c1,
                "conversation": conv1,
                "subject": "Double Charge on Order #SE-84920",
                "description": conv1.summary,
                "category": "Billing & Payments",
                "priority": Ticket.Priority.CRITICAL,
                "status": Ticket.Status.IN_PROGRESS,
                "assigned_team": billing_team,
                "assigned_agent": staff_users["agent.two@shopease.com"]
            }
        )
        TicketComment.objects.get_or_create(
            ticket=t1,
            author=staff_users["agent.two@shopease.com"],
            defaults={"is_internal": True, "content": "Checking merchant portal with Stripe. One hold is pending void."}
        )

        # Conversation 2: Order Inquiry
        conv2, _ = Conversation.objects.get_or_create(
            workspace=workspace,
            customer=c2,
            defaults={
                "channel": Conversation.Channel.BROWSER_VOICE,
                "status": Conversation.Status.COMPLETED,
                "intent": "Order Tracking & Delivery",
                "sentiment": Conversation.Sentiment.POSITIVE,
                "urgency": Conversation.Urgency.LOW,
                "summary": "Customer checked shipping timelines for standard delivery. AI referenced 3-5 business days policy."
            }
        )
        # Ticket 2 (Resolved)
        t2, _ = Ticket.objects.get_or_create(
            workspace=workspace,
            ticket_number="TK-260102",
            defaults={
                "customer": c2,
                "conversation": conv2,
                "subject": "Delivery Timeline Inquiry",
                "description": conv2.summary,
                "category": "Order Tracking & Delivery",
                "priority": Ticket.Priority.LOW,
                "status": Ticket.Status.RESOLVED,
                "assigned_team": order_team,
                "assigned_agent": staff_users["agent.one@shopease.com"],
                "resolved_at": timezone.now()
            }
        )

        # Ticket 3: Open General Ticket
        Ticket.objects.get_or_create(
            workspace=workspace,
            ticket_number="TK-260103",
            defaults={
                "customer": c3,
                "subject": "Product Compatibility Question",
                "description": "Visitor asked whether headphones support Bluetooth 5.3 multipoint audio.",
                "category": "General Support",
                "priority": Ticket.Priority.MEDIUM,
                "status": Ticket.Status.OPEN,
                "assigned_team": order_team,
            }
        )

        self.stdout.write(self.style.SUCCESS("[+] Demo data seeded successfully!"))
        self.stdout.write(f"    Company Portal   : /shopease/")
        self.stdout.write(f"    Customer Widget  : /widget/{workspace.public_key}/demo/")
        self.stdout.write(f"    Owner Login      : owner@shopease.com / ShopEase@123")
        self.stdout.write(f"    Multi-Team Agent : agent.two@shopease.com / ShopEase@123 (In Order & Billing)")

