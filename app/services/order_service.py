import uuid
from decimal import Decimal
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.models.product import Product
from app.models.order import Order, OrderItem
from app.models.outbox import OutboxEvent
from app.schemas.order import OrderCreate
from sqlalchemy.orm import selectinload


class InsufficientStockError(Exception):
    def __init__(self, product_id: uuid.UUID):
        self.product_id = product_id


class ProductNotFoundError(Exception):
    def __init__(self, product_id: uuid.UUID):
        self.product_id = product_id


async def get_order_by_idempotency_key(db: AsyncSession, key: str) -> Order | None:
    result = await db.execute(
        select(Order).options(selectinload(Order.items)).where(Order.idempotency_key == key)
    )
    return result.scalar_one_or_none()


async def create_order(
    db: AsyncSession,
    payload: OrderCreate,
    idempotency_key: str | None,
) -> Order:
    if idempotency_key:
        existing = await get_order_by_idempotency_key(db, idempotency_key)
        if existing:
            return existing #why 2 times checking key?

    product_ids = [item.product_id for item in payload.items]
    result = await db.execute(select(Product).where(Product.id.in_(product_ids)))
    products = {p.id: p for p in result.scalars().all()}

    for item in payload.items:
        if item.product_id not in products:
            raise ProductNotFoundError(item.product_id)

    order_items_data = []
    total = Decimal("0")

    for item in payload.items:
        product = products[item.product_id]
        stmt = (
            update(Product)
            .where(Product.id == item.product_id, Product.stock >= item.quantity)
            .values(stock=Product.stock - item.quantity)
        )
        result = await db.execute(stmt)
        if result.rowcount == 0:
            raise InsufficientStockError(item.product_id)

        price_snapshot = product.price
        total += price_snapshot * item.quantity
        order_items_data.append(
            OrderItem(
                product_id=item.product_id,
                quantity=item.quantity,
                price_snapshot=price_snapshot,
            )
        )

    order = Order(
        customer_id=payload.customer_id,
        total=total,
        idempotency_key=idempotency_key,
        items=order_items_data,
    )
    db.add(order)
    await db.flush()

    outbox_event = OutboxEvent(
        aggregate_id=order.id,
        event_type="order.created",
        payload={
            "order_id": str(order.id),
            "customer_id": str(order.customer_id),
            "total": str(order.total),
            "items": [
                {
                    "product_id": str(i.product_id),
                    "quantity": i.quantity,
                    "price": str(i.price_snapshot),
                }
                for i in order_items_data
            ],
        },
    )
    db.add(outbox_event)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await get_order_by_idempotency_key(db, idempotency_key)
        if existing:
            return existing#2times check?
        raise

    result = await db.execute(
        select(Order).options(selectinload(Order.items)).where(Order.id == order.id)
    )
    return result.scalar_one()