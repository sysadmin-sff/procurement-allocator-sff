from fastapi import FastAPI

from app.api.allocation import router as allocation_router
from app.api.health import router as health_router
from app.api.material import router as material_router
from app.api.price import router as price_router
from app.api.supplier import router as supplier_router

app = FastAPI(title="procurement-allocator")

app.include_router(health_router)
app.include_router(allocation_router)
app.include_router(supplier_router)
app.include_router(material_router)
app.include_router(price_router)
