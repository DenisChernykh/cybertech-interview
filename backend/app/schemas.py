from typing import Annotated

from pydantic import BaseModel, EmailStr, Field


class Line(BaseModel):
    product_id: int
    quantity: Annotated[int, Field(strict=True, ge=1, le=50)]


class Basket(BaseModel):
    items: Annotated[list[Line], Field(min_length=1, max_length=20)]


class Checkout(Basket):
    customer_name: Annotated[str, Field(min_length=2, max_length=120)]
    email: EmailStr
    address: Annotated[str, Field(min_length=5, max_length=500)]
    quote_hash: str
    checkout_key: Annotated[str, Field(min_length=16, max_length=64)]


class Reason(BaseModel):
    reason: Annotated[str, Field(min_length=3, max_length=500)]


class Login(BaseModel):
    password: Annotated[str, Field(max_length=300)]
