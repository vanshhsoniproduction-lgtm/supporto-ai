from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from apps.workspaces.models import Workspace, WorkspaceMembership, WorkspaceSettings, WorkspaceAuthorizedEmail
from apps.teams.models import Team, TeamMembership
from apps.customers.models import Customer
from apps.conversations.models import Conversation, Message
from apps.tickets.models import Ticket, TicketComment, TicketEvent, TicketAssignment
from apps.knowledge_base.models import KnowledgeDocument
from apps.knowledge_base.services.document_processor import document_processor
from apps.ai_engine.models import AgentConfiguration
from apps.voice_support.models import VoiceConfiguration, IVRMenu, IVROption
from apps.emails.models import MailboxConnection, InboundEmail, TicketProposal
from apps.emails.services.email_triage import email_triage_service

User = get_user_model()

class Command(BaseCommand):
    help = "Seeds initial development demo data including ShopEase workspace, authorized emails, teams, staff, knowledge base chunks, and email triage proposals."

    def handle(self, *args, **options):
        self.stdout.write("[*] Seeding Supporto AI demo data...")

        # 0. Platform Admin
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

        # 2. Teams: Order Support & Billing Support
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

        # 3. Workspace Owner
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

        WorkspaceAuthorizedEmail.objects.get_or_create(
            workspace=workspace,
            normalized_email="owner@shopease.com",
            defaults={
                "email": "owner@shopease.com",
                "assigned_role": WorkspaceMembership.Role.OWNER,
                "status": WorkspaceAuthorizedEmail.Status.AUTHORIZED,
                "linked_user": owner,
                "invited_by": admin_user,
            }
        )

        # Developer / Lead Google Accounts pre-authorized as OWNER
        for dev_email in ["vanshhsoni.production@gmail.com", "sonivanshmaster@gmail.com", "vanshhsoni@gmail.com"]:
            dev_user, _ = User.objects.get_or_create(
                email=dev_email,
                defaults={"first_name": "Vansh", "last_name": "Soni", "username": dev_email}
            )
            WorkspaceMembership.objects.get_or_create(
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

        # 4. Staff Users & Explicit Platform-Admin Email Authorizations
        staff_data = [
            ("agent.one@shopease.com", "Sarah", "Connor", WorkspaceMembership.Role.AGENT, [order_team]),
            ("agent.two@shopease.com", "Marcus", "Wright", WorkspaceMembership.Role.AGENT, [order_team, billing_team]),
            ("agent.three@shopease.com", "Kyle", "Reese", WorkspaceMembership.Role.AGENT, [billing_team]),
            ("manager@shopease.com", "John", "Connor", WorkspaceMembership.Role.MANAGER, [order_team, billing_team]),
        ]

        staff_users = {}
        for email, fn, ln, role, assigned_teams in staff_data:
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
            auth_rec, _ = WorkspaceAuthorizedEmail.objects.get_or_create(
                workspace=workspace,
                normalized_email=email,
                defaults={
                    "email": email,
                    "assigned_role": role,
                    "status": WorkspaceAuthorizedEmail.Status.AUTHORIZED,
                    "linked_user": u,
                    "invited_by": admin_user,
                }
            )
            auth_rec.assigned_teams.set(assigned_teams)
            staff_users[email] = u

            for t in assigned_teams:
                TeamMembership.objects.get_or_create(
                    team=t,
                    user=u,
                    defaults={"role": TeamMembership.Role.MEMBER}
                )

        # 5. Knowledge Base FAQs with Chunk Indexing
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
            doc, _ = KnowledgeDocument.objects.get_or_create(
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
            document_processor.chunk_and_index(doc)

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
            }
        )

        # 7. Mailbox Connection & Seeded Inbound Emails
        mailbox, _ = MailboxConnection.objects.get_or_create(
            workspace=workspace,
            email_address="support@shopease.com",
            defaults={
                "provider": MailboxConnection.Provider.GMAIL,
                "status": MailboxConnection.Status.ACTIVE,
                "provider_account_id": "shopease_support_inbox",
                "last_successful_sync_at": timezone.now(),
            }
        )

        # Demo Inbound Emails & Proposals
        sample_emails = [
            (
                "msg_seed_001",
                "alex.rivera@example.com",
                "Alex Rivera",
                "Double charge on my credit card for Order #SE-99124",
                "Hello Support, I noticed my bank account was charged twice for $149.99 on Order #SE-99124. This is an unauthorized duplicate charge. Please refund the duplicate immediately as this is urgent.",
                "CRITICAL",
                "PAYMENT_ISSUE",
                billing_team,
            ),
            (
                "msg_seed_002",
                "jordan.lee@example.com",
                "Jordan Lee",
                "Order status inquiry for package #SE-88210",
                "Hi there, I placed an order three days ago for smart wireless headphones. Can you please check when it is scheduled to arrive at my address?",
                "LOW",
                "ORDER_STATUS",
                order_team,
            ),
            (
                "msg_seed_003",
                "sam.taylor@example.com",
                "Sam Taylor",
                "Application crashing on checkout page",
                "Whenever I click proceed to payment, the page freezes and shows a 500 server error. I have tried clearing cookies but it still fails.",
                "HIGH",
                "TECHNICAL_SUPPORT",
                order_team,
            ),
        ]

        for p_id, s_email, s_name, subj, body, urg, intent, rec_team in sample_emails:
            inbound_email, _ = InboundEmail.objects.get_or_create(
                workspace=workspace,
                provider_message_id=p_id,
                defaults={
                    "mailbox_connection": mailbox,
                    "sender_email": s_email,
                    "sender_name": s_name,
                    "recipient": "support@shopease.com",
                    "subject": subj,
                    "original_text_body": body,
                    "normalized_text_body": body,
                    "received_at": timezone.now(),
                    "processing_status": InboundEmail.ProcessingStatus.TICKET_PROPOSED,
                }
            )
            # Run triage pipeline to link customer, conversation, and create proposal
            email_triage_service.process_inbound_email(inbound_email)

        # 8. Sample Customers and Historical Tickets
        c1, _ = Customer.objects.get_or_create(
            workspace=workspace,
            normalized_email="elena.fisher@example.com",
            defaults={"name": "Elena Fisher", "email": "elena.fisher@example.com", "is_anonymous": False, "source": Customer.Source.WIDGET}
        )
        c2, _ = Customer.objects.get_or_create(
            workspace=workspace,
            normalized_email="nathan.drake@example.com",
            defaults={"name": "Nathan Drake", "email": "nathan.drake@example.com", "is_anonymous": False, "source": Customer.Source.VOICE}
        )

        conv1, _ = Conversation.objects.get_or_create(
            workspace=workspace,
            customer=c1,
            defaults={
                "channel": Conversation.Channel.WEB_CHAT,
                "status": Conversation.Status.ACTIVE,
                "intent": "Duplicate Payment Discrepancy",
                "sentiment": Conversation.Sentiment.FRUSTRATED,
                "urgency": Conversation.Urgency.CRITICAL,
                "summary": "Customer reported being charged $89.99 twice for order #SE-84920."
            }
        )

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
        TicketAssignment.objects.get_or_create(
            ticket=t1,
            assigned_by=owner,
            defaults={"new_team": billing_team, "new_agent": staff_users["agent.two@shopease.com"], "reason": "Initial routing"}
        )

        self.stdout.write(self.style.SUCCESS("[+] Demo data seeded successfully!"))
        self.stdout.write(f"    Public Landing    : /")
        self.stdout.write(f"    Platform Admin    : /admin/ (admin@supporto.ai / Supporto@Admin123)")
        self.stdout.write(f"    Platform Login    : /admin/login/")
        self.stdout.write(f"    ShopEase Portal   : /shopease/")
        self.stdout.write(f"    ShopEase Inbox    : /shopease/emails/")
        self.stdout.write(f"    Pending Reviews   : /shopease/emails/review/")
        self.stdout.write(f"    Weekly Insights   : /shopease/analytics/weekly/")
        self.stdout.write(f"    Customer Widget   : /widget/{workspace.public_key}/demo/")
