from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.payments import router as payment_router
from app.api.store import router
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.errors import BusinessError

app = FastAPI(title="Лист — магазин", version="0.1.0")


@app.middleware("http")
async def origin_check(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and not request.url.path.startswith(
        "/api/webhooks/"
    ):
        if request.headers.get("origin") not in settings().trusted_origins.split(","):
            return JSONResponse(
                {"code": "origin_rejected", "message": "Недопустимый источник запроса"},
                status_code=403,
            )
    return await call_next(request)


@app.exception_handler(BusinessError)
async def business_error(request, exc):
    return JSONResponse({"code": exc.code, "message": exc.message}, status_code=exc.status)


@app.get("/api/health")
def health():
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ok"}


app.include_router(payment_router)
app.include_router(router)
