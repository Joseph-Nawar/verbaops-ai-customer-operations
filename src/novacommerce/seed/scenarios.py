"""Stable named references used by later scenario-aware milestones."""

from enum import StrEnum


class SeedScenario(StrEnum):
    CUSTOMER_PRIMARY = "customer_primary"
    CUSTOMER_OTHER = "customer_other"
    ORDER_CANCELLABLE = "order_cancellable"
    ORDER_ALREADY_SHIPPED = "order_already_shipped"
    ORDER_DELIVERED_29D = "order_delivered_29d"
    ORDER_DELIVERED_30D = "order_delivered_30d"
    ORDER_DELIVERED_31D = "order_delivered_31d"
    ORDER_REFUND_499_99 = "order_refund_499_99"
    ORDER_REFUND_500_00 = "order_refund_500_00"
    ORDER_REFUND_501_00 = "order_refund_501_00"
    ORDER_OTHER_CUSTOMER = "order_other_customer"
    PRODUCT_OUT_OF_STOCK = "product_out_of_stock"
    PRODUCT_LOW_STOCK = "product_low_stock"
    PRODUCT_STANDARD_STOCK = "product_standard_stock"
    PRODUCT_499_99 = "product_499_99"
    PRODUCT_500_00 = "product_500_00"
    PRODUCT_501_00 = "product_501_00"
    SLOT_AVAILABLE = "slot_available"
    SLOT_ONE_REMAINING = "slot_one_remaining"
    SLOT_FULL = "slot_full"


SCENARIO_ENTITY_TYPES = {
    **{
        scenario.value: "customer"
        for scenario in SeedScenario
        if scenario.value.startswith("customer_")
    },
    **{scenario.value: "order" for scenario in SeedScenario if scenario.value.startswith("order_")},
    **{
        scenario.value: "product"
        for scenario in SeedScenario
        if scenario.value.startswith("product_")
    },
    **{
        scenario.value: "delivery_slot"
        for scenario in SeedScenario
        if scenario.value.startswith("slot_")
    },
}
