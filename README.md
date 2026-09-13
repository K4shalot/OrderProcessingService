# OrderProcessingService
## Project structure
- alembic/ # database migrations
- app/
- api/routers/
- core/
- models/
- schemas/
- services/
- workers/ # outbox publisher and Kafka consumer
- main.py
- tests/
- docker-compose.yml
- Dockerfile

## Running the app

```bash
docker compose up --build
```

Start:
- `postgres` — database
- `kafka` — single-node broker (KRaft mode)
- `app` — FastAPI service on `http://localhost:8000` or `http://localhost:8000/docs`
- `outbox-worker` — polls the outbox table and publishes events to Kafka
- `order-consumer` — consumes `order.created` events and writes notifications

Apply database migrations (first time, or after model changes):
```bash
docker compose exec app alembic upgrade head
```

## API

- `POST /products` — create a product
- `GET /products` — list products
- `POST /orders` — create an order (supports `Idempotency-Key` header)
- `GET /orders/{id}` — get an order
- `GET /orders` — list orders

Example product payload:
```json
{
  "name": "string",
  "price": 0,
  "stock": 0
}
```

Example order payload:
```json
{
  "customer_id": "uuid",
  "items": [{"product_id": "uuid", "quantity": 2}]
}
```

## Running tests

Tests run against a separate database (`orders_test`) on the same Postgres instance. Create it once:

```bash
docker compose exec postgres psql -U postgres -c "CREATE DATABASE orders_test;"
```

Then run:

```bash
docker compose exec app pytest -v
```

## Concurrency handling

Stock is decremented with a single atomic SQL statement rather than a read-then-write:

```sql
UPDATE products SET stock = stock - :qty WHERE id = :id AND stock >= :qty
```

If the affected row count is 0, there wasn't enough stock, and the request fails with `409 Conflict`. This avoids the classic race condition where two concurrent requests both read the same stock value before either writes — PostgreSQL guarantees the update is atomic at the row level, so only one of two concurrent requests for the last unit of a product succeeds. Covered by `test_concurrent_orders_last_item`.

## Idempotency (Idempotency-Key)

`POST /orders` accepts an `Idempotency-Key` HEADER. On each request:
1. If an order with that key already exists, it's returned as-is — no new order is created, no stock is touched again.
2. If two requests with the same key arrive concurrently and both pass the initial check, a unique constraint on `idempotency_key` prevents a duplicate insert; the request that loses the race catches the resulting `IntegrityError` and returns the existing order instead of failing.

**IMPORTANT**
**Known limitation:** the current implementation doesn't verify that a REUSED IDEMPOTENCY key is paired with the same request payload. Reusing a key with a different body currently returns the ORIGINAL order silently rather than a conflict error.

## Kafka: Transactional Outbox & delivery guarantees

- When an order is created, an `OutboxEvent` row (`event_type=order.created`, `aggregate_id=order_id`, JSON payload) is written to PostgreSQL **in the same transaction** as the order and its items. The event can never be lost, and can never exist without a corresponding order.
- A separate **outbox worker** process polls `outbox_events` for unprocessed rows (`processed_at IS NULL`) using `SELECT ... FOR UPDATE SKIP LOCKED`, allowing multiple worker replicas to run concurrently without processing the same row twice or blocking each other (`docker compose up --scale outbox-worker=3`).
- Events are published to the `orders.events` topic using `aggregate_id` (the order ID) as the Kafka partition key, so all events for the same order stay ordered.
- Kafka delivery is treated as **at-least-once**: the outbox worker retries publishing on failure (with backoff) and only marks a row as processed after a successful send. A crash between publish and marking-processed can result in the same event being published twice.
- The **consumer** is idempotent by construction: it inserts a `Notification` row keyed by `event_id`, which has a unique constraint. A duplicate event triggers an `IntegrityError`, which is caught and ignored — no duplicate notification is ever created, no matter how many times the same event is delivered. Covered by `test_duplicate_kafka_event_creates_one_notification`.
- The consumer commits its Kafka offset only after successfully handling a message; if processing fails, the offset isn't committed and the message is redelivered on the next poll.

## Tests

Covers: successful order creation, insufficient stock, nonexistent product, correct Decimal total calculation, concurrent stock updates on the last available unit, duplicate idempotency key, duplicate Kafka event handling, and outbox event creation alongside the order.
