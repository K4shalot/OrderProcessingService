from aiokafka import AIOKafkaProducer
from app.core.config import settings
import asyncio
import logging
from aiokafka import AIOKafkaProducer
from app.core.config import settings

logger = logging.getLogger("kafka")
_producer: AIOKafkaProducer | None = None


async def create_producer(max_retries: int = 10, delay: float = 3.0) -> AIOKafkaProducer:
    producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_bootstrap_servers)
    for attempt in range(1, max_retries + 1):
        try:
            await producer.start()
            return producer
        except Exception as exc:
            logger.warning("Kafka producer start failed (%s/%s): %s", attempt, max_retries, exc)
            await asyncio.sleep(delay)
    raise RuntimeError("Could not connect to Kafka after retries")

async def get_producer() -> AIOKafkaProducer:
    global _producer
    if _producer is None:
        _producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
        )
        await _producer.start()
    return _producer


async def stop_producer():
    global _producer
    if _producer is not None:
        await _producer.stop()
        _producer = None
        
async def create_producer() -> AIOKafkaProducer:
    producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_bootstrap_servers)
    await producer.start()
    return producer