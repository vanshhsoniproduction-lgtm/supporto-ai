"""
test_orders.py - Comprehensive test suite for the Orders & Shipments SQL data layer,
phone identity verification, tool registry functions, and staff relations.
"""
from decimal import Decimal
from datetime import timedelta
from django.test import TestCase, Client
from django.utils import timezone
from django.contrib.auth import get_user_model

from apps.workspaces.models import Workspace, WorkspaceSettings
from apps.teams.models import Team
from apps.tickets.models import Ticket
from apps.customers.models import Customer
from apps.orders.models import Order, OrderItem, Shipment, ShipmentEvent, ReturnRequest
from apps.orders.utils import normalize_phone, is_valid_phone
from services.ai.tool_registry import tool_registry

User = get_user_model()


class OrdersAndPhoneVerificationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.shopease = Workspace.objects.create(name="ShopEase Test", slug="shopease-test")
        self.expressbeas = Workspace.objects.create(name="ExpressBeas Test", slug="expressbeas-test")

        self.team_orders = Team.objects.create(workspace=self.shopease, name="Order Support", slug="order-support", is_active=True)
        self.team_billing = Team.objects.create(workspace=self.shopease, name="Billing Support", slug="billing-support", is_active=True)

        self.cust_vansh = Customer.objects.create(
            workspace=self.shopease,
            name="Vansh Soni",
            email="vansh@example.com",
            phone="+91 63677 43066",
            normalized_phone="6367743066"
        )
        self.cust_riya = Customer.objects.create(
            workspace=self.shopease,
            name="Riya Sharma",
            email="riya@example.com",
            phone="+91 95715 38144",
            normalized_phone="9571538144"
        )

        now = timezone.now()

        # ShopEase Order 1: Delivered (Vansh)
        self.order_delivered = Order.objects.create(
            workspace=self.shopease,
            customer=self.cust_vansh,
            order_number="SE-84920",
            customer_name="Vansh Soni",
            customer_phone="6367743066",
            customer_email="vansh@example.com",
            status=Order.Status.DELIVERED,
            payment_method=Order.PaymentMethod.CARD,
            payment_status=Order.PaymentStatus.PAID,
            subtotal=Decimal("4999.00"),
            total=Decimal("4999.00"),
            shipping_address="12, Civil Lines",
            city="Jaipur",
            pincode="302006",
            placed_at=now - timedelta(days=5),
            estimated_delivery=now - timedelta(days=3),
            delivered_at=now - timedelta(days=3),
            carrier="FedEx Express (FX-94001118)",
            return_eligible_until=now + timedelta(days=25)
        )
        OrderItem.objects.create(
            order=self.order_delivered,
            sku="ANC-HP-01",
            name="Wireless Noise-Canceling Headphones",
            quantity=1,
            unit_price=Decimal("4999.00")
        )

        # ReturnRequest for Order 1
        ReturnRequest.objects.create(
            order=self.order_delivered,
            type=ReturnRequest.Type.RETURN_AND_REFUND,
            reason="Sound profile too bass heavy",
            status=ReturnRequest.Status.PICKUP_SCHEDULED,
            refund_amount=Decimal("4999.00"),
            refund_method="Original Payment Card",
            refund_status=ReturnRequest.RefundStatus.PENDING,
            expected_refund_by=now + timedelta(days=2)
        )

        # ShopEase Order 2: Placed / Cancellable (Vansh)
        self.order_placed = Order.objects.create(
            workspace=self.shopease,
            customer=self.cust_vansh,
            order_number="SE-84922",
            customer_name="Vansh Soni",
            customer_phone="6367743066",
            customer_email="vansh@example.com",
            status=Order.Status.PLACED,
            payment_method=Order.PaymentMethod.UPI,
            payment_status=Order.PaymentStatus.PAID,
            subtotal=Decimal("1499.00"),
            total=Decimal("1499.00"),
            shipping_address="12, Civil Lines",
            city="Jaipur",
            pincode="302006",
            placed_at=now - timedelta(hours=2),
            estimated_delivery=now + timedelta(days=2),
            carrier="Bluedart Surface"
        )
        OrderItem.objects.create(
            order=self.order_placed,
            sku="MAG-CHG-01",
            name="Magnetic Wireless Charging Pad 15W",
            quantity=1,
            unit_price=Decimal("1499.00")
        )

        # ExpressBeas Shipment (Vansh)
        self.shipment = Shipment.objects.create(
            workspace=self.expressbeas,
            awb="152785863851740",
            service_type=Shipment.ServiceType.SURFACE,
            weight_kg=Decimal("1.20"),
            origin_city="Ghaziabad",
            destination_city="Jaipur",
            sender_name="Cloudtail India",
            sender_phone="9811002233",
            receiver_name="Vansh Soni",
            receiver_phone="6367743066",
            status=Shipment.Status.DELIVERED,
            current_location="Jaipur Delivery Center",
            delivered_at=now - timedelta(days=1)
        )
        ShipmentEvent.objects.create(
            shipment=self.shipment,
            status="Pickup Done",
            location="Ghaziabad Facility",
            occurred_at=now - timedelta(days=3),
            remarks="Package collected"
        )
        ShipmentEvent.objects.create(
            shipment=self.shipment,
            status="In Transit",
            location="Delhi Main Sort Hub",
            occurred_at=now - timedelta(days=2),
            remarks="Inward scan"
        )
        ShipmentEvent.objects.create(
            shipment=self.shipment,
            status="Delivered",
            location="Jaipur Delivery Center",
            occurred_at=now - timedelta(days=1),
            remarks="Delivered to recipient with OTP"
        )

    # 1. Phone Normalization Tests
    def test_phone_normalization_various_formats(self):
        """Validates normalize_phone handles all standard Indian mobile shapes."""
        self.assertEqual(normalize_phone("+91 63677 43066"), "6367743066")
        self.assertEqual(normalize_phone("06367743066"), "6367743066")
        self.assertEqual(normalize_phone("6367743066"), "6367743066")
        self.assertEqual(normalize_phone("+91-95715-38144"), "9571538144")
        self.assertEqual(normalize_phone("91 9571538144"), "9571538144")
        self.assertEqual(normalize_phone("   +91 (636) 774-3066  "), "6367743066")

        self.assertTrue(is_valid_phone("6367743066"))
        self.assertTrue(is_valid_phone("+91 95715 38144"))
        self.assertFalse(is_valid_phone("12345"))
        self.assertFalse(is_valid_phone("5123456789"))  # Does not start with 6-9
        self.assertFalse(is_valid_phone(""))

    # 2. Phone Identity Verification Tests
    def test_order_lookup_with_matching_phone_succeeds(self):
        """When phone matches record, full order details and items are returned."""
        res = tool_registry.get_order_details(self.shopease.id, "SE-84920", phone="+91 63677 43066")
        self.assertTrue(res["success"])
        self.assertTrue(res["verified"])
        order_data = res["order"]
        self.assertEqual(order_data["order_number"], "SE-84920")
        self.assertEqual(order_data["customer_name"], "Vansh Soni")
        self.assertEqual(len(order_data["items"]), 1)
        self.assertEqual(order_data["items"][0]["name"], "Wireless Noise-Canceling Headphones")
        self.assertEqual(order_data["status"], Order.Status.DELIVERED)

    def test_order_lookup_with_mismatched_phone_leaks_nothing(self):
        """When phone does NOT match record, zero order details are leaked."""
        res = tool_registry.get_order_details(self.shopease.id, "SE-84920", phone="9571538144")  # Riya's phone
        self.assertFalse(res["success"])
        self.assertFalse(res.get("verified", False))
        self.assertNotIn("order", res)
        self.assertIn("couldn't verify", res["error"].lower())

    def test_order_lookup_without_phone_prompts_safely(self):
        """When no phone is provided, prompt for phone and leak zero details."""
        res = tool_registry.get_order_details(self.shopease.id, "SE-84920", phone="")
        self.assertFalse(res["success"])
        self.assertTrue(res.get("needs_phone"))
        self.assertNotIn("order", res)
        self.assertIn("registered 10-digit phone number", res["error"])

    # 3. Workspace Scoping Tests
    def test_cross_workspace_isolation_blocks_queries(self):
        """ShopEase order in ExpressBeas returns not found; ExpressBeas AWB in ShopEase returns not found."""
        # Query SE-84920 in ExpressBeas
        res_eb = tool_registry.get_order_details(self.expressbeas.id, "SE-84920", phone="6367743066")
        self.assertFalse(res_eb["success"])
        self.assertIn("not found", res_eb["error"].lower())

        # Query AWB in ShopEase
        res_se = tool_registry.get_shipment_tracking(self.shopease.id, "152785863851740", phone="6367743066")
        self.assertFalse(res_se["success"])
        self.assertIn("not found", res_se["error"].lower())

    # 4. Shipment Tracking Tests
    def test_shipment_tracking_returns_full_timeline(self):
        """Verified tracking returns complete event timeline in order."""
        res = tool_registry.get_shipment_tracking(self.expressbeas.id, "152785863851740", phone="6367743066")
        self.assertTrue(res["success"])
        self.assertTrue(res["verified"])
        shipment = res["shipment"]
        self.assertEqual(shipment["awb"], "152785863851740")
        self.assertEqual(shipment["status"], Shipment.Status.DELIVERED)
        self.assertEqual(len(shipment["timeline"]), 3)
        self.assertEqual(shipment["timeline"][0]["status"], "Pickup Done")
        self.assertEqual(shipment["timeline"][-1]["status"], "Delivered")

    def test_shipment_tracking_sender_phone_verification(self):
        """Sender phone also has legitimate access to consignment status."""
        res = tool_registry.get_shipment_tracking(self.expressbeas.id, "152785863851740", phone="9811002233")
        self.assertTrue(res["success"])
        self.assertTrue(res["verified"])

    # 5. Customer Orders List Tests
    def test_list_customer_orders_scopes_to_phone(self):
        """Listing orders by phone returns only orders matching that phone."""
        res_vansh = tool_registry.list_customer_orders(self.shopease.id, phone="6367743066")
        self.assertTrue(res_vansh["success"])
        self.assertEqual(len(res_vansh["orders"]), 2)
        order_numbers = [o["order_number"] for o in res_vansh["orders"]]
        self.assertIn("SE-84920", order_numbers)
        self.assertIn("SE-84922", order_numbers)

        res_riya = tool_registry.list_customer_orders(self.shopease.id, phone="9571538144")
        self.assertTrue(res_riya["success"])
        self.assertEqual(len(res_riya["orders"]), 0)

    # 6. Order Cancellation & Auto-Ticket Linking Tests
    def test_cancel_order_placed_status_succeeds_and_creates_ticket(self):
        """Cancelling a PLACED order transitions status to CANCELLED and links a Ticket."""
        res = tool_registry.cancel_order(
            workspace_id=self.shopease.id,
            order_number="SE-84922",
            phone="6367743066",
            reason="Found a better price elsewhere"
        )
        self.assertTrue(res["success"])
        self.assertTrue(res["cancelled"])
        self.assertIsNotNone(res["ticket_number"])

        # Check Order status in DB
        self.order_placed.refresh_from_db()
        self.assertEqual(self.order_placed.status, Order.Status.CANCELLED)
        self.assertIsNotNone(self.order_placed.cancelled_at)

        # Check Ticket in DB
        ticket = Ticket.objects.filter(workspace=self.shopease, ticket_number=res["ticket_number"]).first()
        self.assertIsNotNone(ticket)
        self.assertEqual(ticket.related_order, self.order_placed)
        self.assertEqual(ticket.priority, Ticket.Priority.HIGH)
        self.assertIn("Cancellation", ticket.subject)

    def test_subsequent_cancellation_references_existing_ticket(self):
        """A second cancellation request on the already cancelled order returns existing ticket."""
        res1 = tool_registry.cancel_order(
            workspace_id=self.shopease.id,
            order_number="SE-84922",
            phone="6367743066"
        )
        self.assertTrue(res1["success"])
        ticket_num1 = res1["ticket_number"]

        res2 = tool_registry.cancel_order(
            workspace_id=self.shopease.id,
            order_number="SE-84922",
            phone="6367743066"
        )
        self.assertTrue(res2["success"])
        self.assertEqual(res2["ticket_number"], ticket_num1)
        self.assertIn("already cancelled", res2["message"].lower())

    def test_cancel_order_delivered_is_rejected(self):
        """Cancelling a DELIVERED order is rejected with return window explanation."""
        res = tool_registry.cancel_order(
            workspace_id=self.shopease.id,
            order_number="SE-84920",
            phone="6367743066"
        )
        self.assertFalse(res["success"])
        self.assertFalse(res["cancelled"])
        self.assertIn("cannot be cancelled", res["error"])
        self.assertTrue(res.get("return_eligible"))

    # 7. Return & Refund Status Tests
    def test_get_return_refund_status(self):
        """Returns details for active ReturnRequest."""
        res = tool_registry.get_return_refund_status(self.shopease.id, "SE-84920", phone="6367743066")
        self.assertTrue(res["success"])
        self.assertTrue(res["has_return"])
        ret = res["return_request"]
        self.assertEqual(ret["status"], ReturnRequest.Status.PICKUP_SCHEDULED)
        self.assertIn("4,999", str(ret["refund_amount"]))
        self.assertEqual(ret["refund_status"], ReturnRequest.RefundStatus.PENDING)
