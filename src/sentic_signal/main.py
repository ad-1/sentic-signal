"""Sentic-Signal pipeline entry point.

Pipeline:
    1. Load config from environment.
    2. Build the list of enabled ingestors (Alpha Vantage, Yahoo RSS).
    3. For each ingestor: fetch news, filter by lookback window.
    4. Publish all qualifying NewsItems to the RabbitMQ raw-news queue.

RabbitMQ is the only dispatch target. Downstream consumers (analyst worker,
notifier) are separate microservices that consume from the queue.

Run:
    python -m sentic_signal.main
"""

import logging
import os

from dotenv import load_dotenv

from sentic_signal.ingestor import BaseIngestor, filter_by_lookback
from sentic_signal.ingestor.alpha_vantage import AlphaVantageIngestor
from sentic_signal.ingestor.finnhub import FinnhubIngestor
from sentic_signal.ingestor.yahoo_finance_rss import YahooFinanceIngestor
from sentic_signal.publisher.rabbitmq_publisher import RabbitMQPublisher
from sentic_signal.models import NewsItem

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Required environment variable '{name}' is not set. Check your .env file.")
    return value


def _load_config() -> dict:
    raw_tickers = os.getenv("TICKERS", "AAPL,TSLA,NVDA")
    tickers = [t.strip().upper() for t in raw_tickers.split(",") if t.strip()]

    lookback_minutes = int(os.getenv("NEWS_LOOKBACK_MINUTES", "60"))
    relevance_threshold = float(os.getenv("NEWS_RELEVANCE_THRESHOLD", "0.5"))
    dry_run = os.getenv("DRY_RUN", "false").lower() in ("1", "true", "yes")

    # Alpha Vantage (optional — if key is absent, ingestor is skipped).
    alpha_vantage_key = os.getenv("ALPHA_VANTAGE_KEY", "")

    # Finnhub (optional — if key is absent, ingestor is skipped).
    finnhub_api_key = os.getenv("FINNHUB_API_KEY", "")

    # Yahoo Finance RSS (free, no key required — enabled by default).
    yahoo_rss_enabled = os.getenv("YAHOO_RSS_ENABLED", "true").lower() in ("1", "true", "yes")

    # RabbitMQ — required.
    rabbitmq_host = _require_env("RABBITMQ_HOST")
    rabbitmq_port = int(os.getenv("RABBITMQ_PORT", "5672"))
    rabbitmq_queue = os.getenv("RABBITMQ_QUEUE", "raw-news")

    return {
        "tickers": tickers,
        "lookback_minutes": lookback_minutes,
        "relevance_threshold": relevance_threshold,
        "dry_run": dry_run,
        "alpha_vantage_key": alpha_vantage_key,
        "finnhub_api_key": finnhub_api_key,
        "yahoo_rss_enabled": yahoo_rss_enabled,
        "rabbitmq_host": rabbitmq_host,
        "rabbitmq_port": rabbitmq_port,
        "rabbitmq_queue": rabbitmq_queue,
    }


# ---------------------------------------------------------------------------
# Ingestor runner
# ---------------------------------------------------------------------------


def _build_ingestors(config: dict) -> list[BaseIngestor]:
    """Construct the list of enabled ingestors from config."""
    ingestors: list[BaseIngestor] = []

    if config["alpha_vantage_key"]:
        ingestors.append(AlphaVantageIngestor(api_key=config["alpha_vantage_key"]))
        logger.info("Alpha Vantage ingestor enabled.")
    else:
        logger.info("Alpha Vantage ingestor disabled (ALPHA_VANTAGE_KEY not set).")

    if config["finnhub_api_key"]:
        ingestors.append(FinnhubIngestor(api_key=config["finnhub_api_key"]))
        logger.info("Finnhub ingestor enabled.")
    else:
        logger.info("Finnhub ingestor disabled (FINNHUB_API_KEY not set).")

    if config["yahoo_rss_enabled"]:
        ingestors.append(YahooFinanceIngestor())
        logger.info("Yahoo Finance RSS ingestor enabled.")

    return ingestors


def _run_ingestors(ingestors: list[BaseIngestor], config: dict) -> list[NewsItem]:
    """Run all ingestors and return the merged, lookback-filtered result."""
    all_items: list[NewsItem] = []

    for ingestor in ingestors:
        try:
            items = ingestor.fetch_news(
                tickers=config["tickers"],
                relevance_threshold=config["relevance_threshold"],
            )
            recent = filter_by_lookback(items, config["lookback_minutes"])
            logger.info(
                "[%s] %d items fetched, %d within lookback window.",
                ingestor.source_provider,
                len(items),
                len(recent),
            )
            all_items.extend(recent)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Ingestor %s failed: %s — continuing with remaining ingestors.",
                ingestor.source_provider,
                exc,
            )

    return all_items


# ---------------------------------------------------------------------------
# Dispatch paths
# ---------------------------------------------------------------------------


def _publish_to_queue(items: list[NewsItem], config: dict) -> None:
    """Publish news items to the RabbitMQ raw-news queue."""
    publisher = RabbitMQPublisher(
        host=config["rabbitmq_host"],
        port=config["rabbitmq_port"],
        queue_name=config["rabbitmq_queue"],
    )
    try:
        publisher.connect()
        published = publisher.publish_news_items(items)
        logger.info(
            "Published %d / %d items to queue '%s'.",
            published,
            len(items),
            config["rabbitmq_queue"],
        )
    finally:
        publisher.close()





# ---------------------------------------------------------------------------
# Pipeline entry points
# ---------------------------------------------------------------------------


def run(config: dict) -> None:
    ingestors = _build_ingestors(config)

    if not ingestors:
        logger.warning("No ingestors configured. Exiting.")
        return

    all_items = _run_ingestors(ingestors, config)
    logger.info("Total qualifying news items: %d", len(all_items))

    if not all_items:
        logger.info("No news items to process — pipeline complete.")
        return

    _publish_to_queue(all_items, config)


def main() -> None:
    logger.info("Sentic-Signal pipeline starting.")
    config = _load_config()
    logger.info(
        "Tickers: %s | Lookback: %d min | Queue: %s",
        config["tickers"],
        config["lookback_minutes"],
        config["rabbitmq_queue"],
    )
    run(config)
    logger.info("Pipeline complete.")


if __name__ == "__main__":
    main()
