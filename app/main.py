from fastapi import FastAPI
from app.api.routers import products, orders

app = FastAPI()

app.include_router(products.router)
app.include_router(orders.router)

@app.get("/health")
def health():
    return {"status": "ok"}