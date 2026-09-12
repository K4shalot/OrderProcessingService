import uuid
import pytest
from sqlalchemy import select

from app.workers.order_consumer import handle_order_created
from app.models.notification import Notification
from tests.conftest import TestSessionLocal


@pytest.mark.asyncio
async def test_duplicate_kafka_event_creates_one_notification(db_session):
    event_id = str(uuid.uuid4())
    order_id = str(uuid.uuid4())
    event = {"event_id": event_id, "event_type": "order.created", "data": {"order_id": order_id}}

    await handle_order_created(event, session_maker=TestSessionLocal)
    await handle_order_created(event, session_maker=TestSessionLocal)

    result = await db_session.execute(
        select(Notification).where(Notification.event_id == uuid.UUID(event_id))
    )
    assert len(result.scalars().all()) == 1