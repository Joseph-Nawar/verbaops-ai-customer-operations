"""Composition router for the M2C read-only API."""

from fastapi import APIRouter

from novacommerce.api.v1.customers import router as customers_router
from novacommerce.api.v1.delivery_slots import router as delivery_slots_router
from novacommerce.api.v1.orders import router as orders_router
from novacommerce.api.v1.products import router as products_router
from novacommerce.api.v1.write_orders import router as write_orders_router
from novacommerce.api.v1.write_refunds import router as write_refunds_router
from novacommerce.api.v1.write_reschedule import router as write_reschedule_router
from novacommerce.api.v1.write_returns import router as write_returns_router
from novacommerce.api.v1.write_tickets import router as write_tickets_router

router = APIRouter(prefix="/v1")
router.include_router(customers_router)
router.include_router(orders_router)
router.include_router(products_router)
router.include_router(delivery_slots_router)
router.include_router(write_orders_router)
router.include_router(write_reschedule_router)
router.include_router(write_returns_router)
router.include_router(write_refunds_router)
router.include_router(write_tickets_router)
