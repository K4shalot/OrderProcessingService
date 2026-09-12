import asyncio
import json
import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session_maker
from app.core.kafka import create_producer
from app.models.outbox import OutboxEvent
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("outbox_worker")

TOPIC = "orders.events"
POLL_INTERVAL = 1.0
BATCH_SIZE = 20
MAX_RETRIES = 3


async def fetch_batch(db: AsyncSession) -> list[OutboxEvent]:
    result = await db.execute(
        select(OutboxEvent)
        .where(OutboxEvent.processed_at.is_(None))
        .order_by(OutboxEvent.created_at)
        .limit(BATCH_SIZE)
        .with_for_update(skip_locked=True)
    )
    return list(result.scalars().all())


async def mark_processed(db: AsyncSession, event_id) -> None:
    await db.execute(
        update(OutboxEvent)
        .where(OutboxEvent.id == event_id)
        .values(processed_at=datetime.now(timezone.utc))
    )


async def publish_event(producer, event: OutboxEvent) -> None:
    payload = json.dumps(
        {
            "event_id": str(event.id),
            "event_type": event.event_type,
            "aggregate_id": str(event.aggregate_id),
            "data": event.payload,
        }
    ).encode("utf-8")

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            await producer.send_and_wait(
                TOPIC, value=payload, key=str(event.aggregate_id).encode("utf-8")
            )
            return
        except Exception as exc:
            logger.warning(
                "Publish attempt %s/%s failed for event %s: %s",
                attempt, MAX_RETRIES, event.id, exc,
            )
            if attempt == MAX_RETRIES:
                raise
            await asyncio.sleep(2 ** attempt)


async def process_batch(producer) -> int:
    async with async_session_maker() as db:
        events = await fetch_batch(db)
        if not events:
            return 0

        for event in events:
            try:
                await publish_event(producer, event)
                await mark_processed(db, event.id)
            except Exception:
                logger.exception("Giving up on event %s for now, will retry next poll", event.id)
                continue

        await db.commit()
        return len(events)


async def run_worker() -> None:
    producer = await create_producer()
    logger.info("Outbox worker started")
    try:
        while True:
            count = await process_batch(producer)
            if count == 0:
                await asyncio.sleep(POLL_INTERVAL)
    finally:
        await producer.stop()


if __name__ == "__main__":
    asyncio.run(run_worker())