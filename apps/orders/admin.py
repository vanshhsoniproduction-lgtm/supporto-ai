from django.contrib import admin
from apps.orders.models import Order, OrderItem, Shipment, ShipmentEvent, ReturnRequest


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


class ReturnRequestInline(admin.StackedInline):
    model = ReturnRequest
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ["order_number", "workspace", "customer_name", "customer_phone", "status", "payment_status", "total", "placed_at"]
    list_filter = ["workspace", "status", "payment_status", "payment_method"]
    search_fields = ["order_number", "customer_name", "customer_phone", "customer_email"]
    inlines = [OrderItemInline, ReturnRequestInline]


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ["name", "order", "quantity", "unit_price", "sku"]
    search_fields = ["name", "sku", "order__order_number"]


class ShipmentEventInline(admin.TabularInline):
    model = ShipmentEvent
    extra = 0


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = ["awb", "workspace", "service_type", "origin_city", "destination_city", "receiver_name", "receiver_phone", "status", "estimated_delivery"]
    list_filter = ["workspace", "status", "service_type"]
    search_fields = ["awb", "receiver_name", "receiver_phone", "sender_name", "sender_phone"]
    inlines = [ShipmentEventInline]


@admin.register(ShipmentEvent)
class ShipmentEventAdmin(admin.ModelAdmin):
    list_display = ["shipment", "status", "location", "occurred_at"]
    list_filter = ["status"]
    search_fields = ["shipment__awb", "location", "status", "remarks"]


@admin.register(ReturnRequest)
class ReturnRequestAdmin(admin.ModelAdmin):
    list_display = ["order", "type", "status", "refund_amount", "refund_status", "expected_refund_by", "created_at"]
    list_filter = ["type", "status", "refund_status"]
    search_fields = ["order__order_number", "reason"]

