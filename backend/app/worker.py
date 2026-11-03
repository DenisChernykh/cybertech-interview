import logging
import time

from app.services.processing import tick


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
