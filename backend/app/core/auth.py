import hashlib
import secrets
from datetime import timedelta

from fastapi import Depends, Request, Response
from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.core.db import get_db
from app.core.errors import BusinessError
from app.models import Session
from app.models.store import now, uid


def token_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def current(request: Request, db: DBSession, role: str):
    token = request.cookies.get("manager_session" if role == "manager" else "shop_session", "")
    item = db.get(Session, token_hash(token))
    if not item or item.expires_at <= now() or item.role != role:
        raise BusinessError(
            "unauthorized", "Необходим вход" if role == "manager" else "Сессия истекла", 401
        )
    return item


def guest(request: Request, db: DBSession = Depends(get_db)):
    return current(request, db, "guest")


def manager(request: Request, db: DBSession = Depends(get_db)):
    return current(request, db, "manager")


def new_session(db, response: Response, role):
    token = secrets.token_urlsafe(32)
    owner = uid()
    db.add(
        Session(
            token_hash=token_hash(token),
            role=role,
            owner_id=owner,
            expires_at=now() + timedelta(days=7 if role == "manager" else 30),
        )
    )
    db.commit()
    response.set_cookie(
        "manager_session" if role == "manager" else "shop_session",
        token,
        httponly=True,
        secure=settings().cookie_secure,
        samesite="lax",
        max_age=(7 if role == "manager" else 30) * 86400,
    )
    return owner
