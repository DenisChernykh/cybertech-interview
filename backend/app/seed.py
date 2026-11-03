from decimal import Decimal

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Product

PRODUCTS = [
    (
        "cleanser",
        "Мягкий гель для умывания",
        "Бережное очищение без ощущения стянутости. Для ежедневного ритуала.",
        "Очищение",
        "150 мл",
        "890.00",
        "/images/cleanser.jpg",
    ),
    (
        "serum",
        "Увлажняющая сыворотка",
        "Лёгкая текстура с гиалуроновой кислотой. Уход, который легко вписать в свой день.",
        "Увлажнение",
        "30 мл",
        "1490.00",
        "/images/serum.jpg",
    ),
    (
        "cream",
        "Восстанавливающий крем",
        "Комфорт и мягкость для кожи. Завершающий шаг утреннего и вечернего ухода.",
        "Увлажнение",
        "50 мл",
        "1190.00",
        "/images/cream.jpg",
    ),
    (
        "toner",
        "Тоник с экстрактом зелёного чая",
        "Свежесть после очищения. Невесомый ежедневный уход.",
        "Очищение",
        "200 мл",
        "790.00",
        "/images/toner.jpg",
    ),
]


def main():
    with SessionLocal.begin() as db:
        for sku, name, description, category, volume, price, image in PRODUCTS:
            if not db.scalar(select(Product).where(Product.sku == sku)):
                db.add(
                    Product(
                        sku=sku,
                        name=name,
                        description=description,
                        category=category,
                        volume=volume,
                        price=Decimal(price),
                        image=image,
                        stock=20,
                        reserved=0,
                    )
                )


if __name__ == "__main__":
    main()
