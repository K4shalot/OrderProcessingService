import uuid
import pytest
from sqlalchemy import select

from app.models.outbox import OutboxEvent


@pytest.mark.asyncio
async def test_outbox_event_created_with_order(client, product, db_session):
    response = await client.post(
        "/orders",
        headers={"Idempotency-Key": "key-outbox-1"},
        json={
            "customer_id": str(uuid.uuid4()),
            "items": [{"product_id": str(product.id), "quantity": 1}],
        },
    )
    assert response.status_code == 201
    order_id = response.json()["id"]

    result = await db_session.execute(
        select(OutboxEvent).where(OutboxEvent.aggregate_id == uuid.UUID(order_id))
    )
    event = result.scalar_one_or_none()

    assert event is not None
    assert event.event_type == "order.created"
    assert event.payload["order_id"] == order_id
    assert event.processed_at is None