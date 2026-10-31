from django.db import models
from django.utils import timezone
from apps.workspaces.models import Workspace
from apps.customers.models import Customer
from apps.orders.utils import normalize_phone


class Order(models.Model):
    class PaymentMethod(models.TextChoices):
        UPI = "UPI", "UPI"
        CARD = "Card", "Credit / Debit Card"
        COD = "COD", "Cash on Delivery"
        NETBANKING = "NetBanking", "Net Banking"

    class PaymentStatus(models.TextChoices):
        PAID = "Paid", "Paid"
        PENDING = "Pending", "Pending"
        REFUNDED = "Refunded", "Refunded"
        PARTIALLY_REFUNDED = "Partially refunded", "Partially Refunded"

    class Status(models.TextChoices):
        PLACED = "Placed", "Order Placed"
        PROCESSING = "Processing", "Processing in Warehouse"
        IN_TRANSIT = "In Transit", "In Transit"
        OUT_FOR_DELIVERY = "Out for Delivery", "Out for Delivery"
        DELIVERED = "Delivered", "Delivered"
        CANCELLED = "Cancelled", "Cancelled"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="orders")
    order_number = models.CharField(max_length=64, db_index=True)
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name="orders")
    customer_name = models.CharField(max_length=150)
    customer_phone = models.CharField(max_length=20, db_index=True)
    customer_email = models.EmailField(blank=True)
    status = models.CharField(max_length=50, choices=Status.choices, default=Status.PROCESSING, db_index=True)
    payment_method = models.CharField(max_length=50, choices=PaymentMethod.choices, default=PaymentMethod.UPI)
    payment_status = models.CharField(max_length=50, choices=PaymentStatus.choices, default=PaymentStatus.PAID)
    currency = models.CharField(max_length=10, default="INR")
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)
    shipping_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)
    shipping_address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    pincode = models.CharField(max_length=20, blank=True)
    placed_at = models.DateTimeField(default=timezone.now)
    estimated_delivery = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    carrier = models.CharField(max_length=100, blank=True)
    return_eligible_until = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-placed_at"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "order_number"], name="unique_workspace_order_number")
        ]

    def clean(self):
        super().clean()
        if self.customer_phone:
            self.customer_phone = normalize_phone(self.customer_phone)

    def save(self, *args, **kwargs):
        if self.customer_phone:
            self.customer_phone = normalize_phone(self.customer_phone)
        super().save(*args, **kwargs)

    @property
    def is_cancellable(self) -> bool:
        """Orders can be cancelled before dispatch (Placed or Processing)."""
        return self.status in [self.Status.PLACED, self.Status.PROCESSING] and self.cancelled_at is None

    @property
    def is_return_eligible(self) -> bool:
        """Eligible for return if delivered and within return window."""
        if self.status != self.Status.DELIVERED:
            return False
        if not self.return_eligible_until:
            return False
        return timezone.now() <= self.return_eligible_until

    def __str__(self):
        return f"{self.order_number} - {self.customer_name} ({self.workspace.name})"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    name = models.CharField(max_length=255)
    sku = models.CharField(max_length=100, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)

    @property
    def line_total(self):
        return self.quantity * self.unit_price

    def __str__(self):
        return f"{self.name} x{self.quantity} ({self.order.order_number})"


class Shipment(models.Model):
    class ServiceType(models.TextChoices):
        SURFACE = "Surface", "Surface Express"
        AIR_EXPRESS = "Air Express", "Air Express"
        DOCUMENT = "Document", "Document Courier"

    class Status(models.TextChoices):
        DATA_RECEIVED = "Data Received", "Data Received"
        PICKUP_SCHEDULED = "Pickup Scheduled", "Pickup Scheduled"
        PICKUP_DONE = "Pickup Done", "Pickup Done"
        IN_TRANSIT = "In Transit", "In Transit"
        REACHED_DESTINATION = "Reached at Destination", "Reached at Destination"
        OUT_FOR_DELIVERY = "Out for Delivery", "Out for Delivery"
        DELIVERED = "Delivered", "Delivered"
        DELAYED = "Delayed", "Delayed"
        DELIVERY_FAILED = "Delivery Failed", "Delivery Failed"
        RETURNED_TO_ORIGIN = "Returned to Origin", "Returned to Origin"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="shipments")
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, related_name="shipments")
    awb = models.CharField(max_length=64, db_index=True)
    service_type = models.CharField(max_length=50, choices=ServiceType.choices, default=ServiceType.SURFACE)
    weight_kg = models.DecimalField(max_digits=8, decimal_places=2, default=1.0)
    origin_city = models.CharField(max_length=100)
    destination_city = models.CharField(max_length=100)
    sender_name = models.CharField(max_length=150)
    sender_phone = models.CharField(max_length=20)
    receiver_name = models.CharField(max_length=150)
    receiver_phone = models.CharField(max_length=20, db_index=True)
    status = models.CharField(max_length=50, choices=Status.choices, default=Status.IN_TRANSIT, db_index=True)
    current_location = models.CharField(max_length=150, blank=True)
    estimated_delivery = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    cod_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "awb"], name="unique_workspace_shipment_awb")
        ]

    def clean(self):
        super().clean()
        if self.sender_phone:
            self.sender_phone = normalize_phone(self.sender_phone)
        if self.receiver_phone:
            self.receiver_phone = normalize_phone(self.receiver_phone)

    def save(self, *args, **kwargs):
        if self.sender_phone:
            self.sender_phone = normalize_phone(self.sender_phone)
        if self.receiver_phone:
            self.receiver_phone = normalize_phone(self.receiver_phone)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"AWB {self.awb} ({self.origin_city} -> {self.destination_city}) - {self.status}"


class ShipmentEvent(models.Model):
    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, related_name="events")
    status = models.CharField(max_length=100)
    location = models.CharField(max_length=150)
    occurred_at = models.DateTimeField()
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["occurred_at"]

    def __str__(self):
        return f"[{self.occurred_at.strftime('%d %b %H:%M')}] {self.status} at {self.location}"


class ReturnRequest(models.Model):
    class Type(models.TextChoices):
        RETURN = "Return", "Return"
        REFUND = "Refund", "Refund"
        RETURN_AND_REFUND = "Return+Refund", "Return & Refund"
        REPLACEMENT = "Replacement", "Replacement"

    class Status(models.TextChoices):
        REQUESTED = "Requested", "Requested"
        APPROVED = "Approved", "Approved"
        PICKUP_SCHEDULED = "Pickup Scheduled", "Pickup Scheduled"
        PICKED_UP = "Picked Up", "Picked Up"
        RECEIVED_AND_QC = "Received and QC", "Received and Quality Check"
        REFUND_INITIATED = "Refund Initiated", "Refund Initiated"
        REFUNDED = "Refunded", "Refunded"
        REJECTED = "Rejected", "Rejected"

    class RefundStatus(models.TextChoices):
        NOT_STARTED = "Not started", "Not Started"
        PENDING = "Pending", "Pending"
        PROCESSED = "Processed", "Processed"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="return_requests")
    type = models.CharField(max_length=50, choices=Type.choices, default=Type.RETURN_AND_REFUND)
    reason = models.TextField()
    status = models.CharField(max_length=50, choices=Status.choices, default=Status.REQUESTED, db_index=True)
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)
    refund_method = models.CharField(max_length=50, default="Original Payment Method")
    refund_status = models.CharField(max_length=50, choices=RefundStatus.choices, default=RefundStatus.NOT_STARTED)
    expected_refund_by = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.type} for Order #{self.order.order_number} ({self.status})"

