from fastapi import FastAPI
from app.api.routers import products

app = FastAPI()

app.include_router(products.router)


@app.get("/health")
def health():
    return {"status": "ok"}