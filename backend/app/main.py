from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.allocation import router as allocation_router
from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.material import router as material_router
from app.api.order import router as order_router
from app.api.price import router as price_router
from app.api.price_ingestion import router as price_ingestion_router
from app.api.project import router as project_router
from app.api.purchase_record import router as purchase_record_router
from app.api.supplier import router as supplier_router

app = FastAPI(title="procurement-allocator")

# Frontend runs on Vite's dev server (localhost:5173, falls back to the next
# free port if taken) on a different origin than this API — browsers block
# cross-origin fetch without this even for local dev. Regex covers the whole
# ephemeral range Vite walks through rather than one hardcoded port.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):5\d{3}",
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(project_router)
app.include_router(allocation_router)
app.include_router(order_router)
app.include_router(purchase_record_router)
app.include_router(supplier_router)
app.include_router(material_router)
app.include_router(price_router)
app.include_router(price_ingestion_router)
