import logging
import time

from app.core.db import SessionLocal
from app.services.store import expire_reservations


def tick():
    with SessionLocal.begin() as db:
        expire_reservations(db)


def main():
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            tick()
        except Exception:
            logging.exception("Worker iteration failed")
        time.sleep(2)


if __name__ == "__main__":
    main()
