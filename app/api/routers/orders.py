from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.db import get_db
from app.models.order import Order
from app.schemas.order import OrderCreate, OrderRead
from app.services.order_service import (
    create_order,
    InsufficientStockError,
    ProductNotFoundError,
)

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", response_model=OrderRead, status_code=201)
async def create_order_endpoint(
    payload: OrderCreate,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        order = await create_order(db, payload, idempotency_key)
    except ProductNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"Product {e.product_id} not found")
    except InsufficientStockError as e:
        raise HTTPException(status_code=409, detail=f"Insufficient stock for product {e.product_id}")
    return order


@router.get("/{order_id}", response_model=OrderRead)
async def get_order(order_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Order).options(selectinload(Order.items)).where(Order.id == order_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.get("", response_model=list[OrderRead])
async def list_orders(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Order).options(selectinload(Order.items)))
    return result.scalars().all()