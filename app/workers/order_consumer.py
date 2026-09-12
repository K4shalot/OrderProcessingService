import asyncio
import json
import logging

from aiokafka import AIOKafkaConsumer
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.db import async_session_maker
from app.models.notification import Notification
from app.core.db import async_session_maker as default_session_maker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("order_consumer")

TOPIC = "orders.events"
GROUP_ID = "order-notifications"


async def handle_order_created(event: dict, session_maker=None) -> None:
    session_maker = session_maker or default_session_maker
    event_id = event["event_id"]
    data = event["data"]

    async with session_maker() as db:
        notification = Notification(
            event_id=event_id,
            order_id=data["order_id"],
        )
        db.add(notification)
        try:
            await db.commit()
            logger.info("Notification created for order %s (event %s)", data["order_id"], event_id)
        except IntegrityError:
            await db.rollback()
            logger.info("Duplicate event %s, skipping (already processed)", event_id)


async def run_consumer() -> None:
    consumer = AIOKafkaConsumer(
        TOPIC,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=GROUP_ID,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    await consumer.start()
    logger.info("Consumer started, listening to %s", TOPIC)
    try:
        async for msg in consumer:
            try:
                event = json.loads(msg.value.decode("utf-8"))
                if event.get("event_type") == "order.created":
                    await handle_order_created(event)
                await consumer.commit()
            except Exception:
                logger.exception("Failed to process message, will retry on next poll")
    finally:
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(run_consumer())