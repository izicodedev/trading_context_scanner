"""Run alongside the scanner: python -m app.strategy_worker."""
import logging
import time

from .lab_service import tick


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    logging.info("Strategy worker ready; checking active sessions every 15 seconds")
    while True:
        try:
            tick()
        except Exception:
            logging.exception("Strategy worker could not read sessions")
        time.sleep(15)


if __name__ == "__main__":
    main()
