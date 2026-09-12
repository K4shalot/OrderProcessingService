import asyncio
import uuid
import pytest

from app.models.product import Product


@pytest.mark.asyncio
async def test_create_order_success(client, product):
    response = await client.post(
        "/orders",
        headers={"Idempotency-Key": "key-success-1"},
        json={
            "customer_id": str(uuid.uuid4()),
            "items": [{"product_id": str(product.id), "quantity": 2}],
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["total"] == "100.00"
    assert data["items"][0]["quantity"] == 2
    assert data["items"][0]["price_snapshot"] == "50.00"


@pytest.mark.asyncio
async def test_create_order_correct_total_calculation(client, db_session):
    p1 = Product(name="A", price="10.50", stock=10)
    p2 = Product(name="B", price="3.33", stock=10)
    db_session.add_all([p1, p2])
    await db_session.commit()
    await db_session.refresh(p1)
    await db_session.refresh(p2)

    response = await client.post(
        "/orders",
        headers={"Idempotency-Key": "key-total-1"},
        json={
            "customer_id": str(uuid.uuid4()),
            "items": [
                {"product_id": str(p1.id), "quantity": 3},
                {"product_id": str(p2.id), "quantity": 2},
            ],
        },
    )
    assert response.status_code == 201
    data = response.json()
    # 10.50 * 3 + 3.33 * 2 = 31.50 + 6.66 = 38.16
    assert data["total"] == "38.16"


@pytest.mark.asyncio
async def test_create_order_insufficient_stock(client, product):
    response = await client.post(
        "/orders",
        headers={"Idempotency-Key": "key-stock-1"},
        json={
            "customer_id": str(uuid.uuid4()),
            "items": [{"product_id": str(product.id), "quantity": 999}],
        },
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_create_order_nonexistent_product(client):
    response = await client.post(
        "/orders",
        headers={"Idempotency-Key": "key-404-1"},
        json={
            "customer_id": str(uuid.uuid4()),
            "items": [{"product_id": str(uuid.uuid4()), "quantity": 1}],
        },
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_duplicate_idempotency_key_returns_same_order(client, product):
    payload = {
        "customer_id": str(uuid.uuid4()),
        "items": [{"product_id": str(product.id), "quantity": 1}],
    }
    headers = {"Idempotency-Key": "key-dup-1"}

    r1 = await client.post("/orders", headers=headers, json=payload)
    r2 = await client.post("/orders", headers=headers, json=payload)

    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]

    products_response = await client.get("/products")
    updated = next(p for p in products_response.json() if p["id"] == str(product.id))
    assert updated["stock"] == product.stock - 1


@pytest.mark.asyncio
async def test_concurrent_orders_last_item(client, db_session):
    p = Product(name="Last Item", price="20.00", stock=1)
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)

    async def place_order(key: str):
        return await client.post(
            "/orders",
            headers={"Idempotency-Key": key},
            json={
                "customer_id": str(uuid.uuid4()),
                "items": [{"product_id": str(p.id), "quantity": 1}],
            },
        )

    results = await asyncio.gather(
        place_order("concurrent-1"),
        place_order("concurrent-2"),
    )

    statuses = sorted(r.status_code for r in results)
    assert statuses == [201, 409]