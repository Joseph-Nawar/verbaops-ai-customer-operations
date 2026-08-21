"""Composition router for the M2C read-only API."""

from fastapi import APIRouter

from novacommerce.api.v1.customers import router as customers_router
from novacommerce.api.v1.delivery_slots import router as delivery_slots_router
from novacommerce.api.v1.orders import router as orders_router
from novacommerce.api.v1.products import router as products_router

router = APIRouter(prefix="/v1")
router.include_router(customers_router)
router.include_router(orders_router)
router.include_router(products_router)
router.include_router(delivery_slots_router)
