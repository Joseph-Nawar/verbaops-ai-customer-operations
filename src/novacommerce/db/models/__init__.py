"""Import all NovaCommerce models to register them with Base.metadata."""

from novacommerce.db.models.commerce_event import CommerceEvent
from novacommerce.db.models.customer import Customer
from novacommerce.db.models.delivery_slot import DeliverySlot
from novacommerce.db.models.idempotency import IdempotencyRecord, IdempotencyStatus
from novacommerce.db.models.order import Order, OrderStatus
from novacommerce.db.models.order_item import OrderItem
from novacommerce.db.models.product import Product
from novacommerce.db.models.refund import Refund, RefundStatus
from novacommerce.db.models.return_ import Return, ReturnItem, ReturnStatus
from novacommerce.db.models.shipment import Shipment, ShipmentStatus
from novacommerce.db.models.support_ticket import SupportTicket, SupportTicketStatus

__all__ = [
    "CommerceEvent",
    "Customer",
    "DeliverySlot",
    "IdempotencyRecord",
    "IdempotencyStatus",
    "Order",
    "OrderItem",
    "OrderStatus",
    "Product",
    "Refund",
    "RefundStatus",
    "Return",
    "ReturnItem",
    "ReturnStatus",
    "Shipment",
    "ShipmentStatus",
    "SupportTicket",
    "SupportTicketStatus",
]
