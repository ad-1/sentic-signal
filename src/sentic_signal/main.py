"""Sentic-Signal pipeline entry point.

Pipeline:
    1. Load config from environment.
    2. Resolve PROVIDER — exactly one ingestor per run.
    3. Validate provider-specific secret requirements (fail-fast).
    4. Fetch news for the configured ticker, filter by lookback window.
    5. Publish qualifying NewsItems to the RabbitMQ raw-news queue.

RabbitMQ is the only dispatch target. Downstream consumers (analyst worker,
notifier) are separate microservices that consume from the queue.

PROVIDER must be set to one of: alpha_vantage, finnhub, yahoo_rss.

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
from sentic_signal.models import NewsItem, SourceProvider

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# Providers that require an API key secret in the environment.
_PROVIDER_REQUIRED_SECRETS: dict[str, str] = {
    SourceProvider.ALPHA_VANTAGE: "ALPHA_VANTAGE_KEY",
    SourceProvider.FINNHUB: "FINNHUB_API_KEY",
}

# Only providers with a complete ingestor implementation are valid at runtime.
# Tier 2 providers (stat_news_rss, sec_edgar) are reserved in SourceProvider
# for downstream contract use but have no ingestor yet — exclude them here so
# that an unknown PROVIDER value fails with a clear error rather than passing
# _resolve_provider() and crashing inside _build_ingestor().
_IMPLEMENTED_PROVIDERS: frozenset[str] = frozenset({
    SourceProvider.ALPHA_VANTAGE,
    SourceProvider.FINNHUB,
    SourceProvider.YAHOO_RSS,
})
# Keep _VALID_PROVIDERS as an alias for clarity in error messages.
_VALID_PROVIDERS = _IMPLEMENTED_PROVIDERS


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Required environment variable '{name}' is not set.")
    return value


def _load_ticker() -> str:
    ticker = os.getenv("TICKER", "AAPL").strip().upper()
    if not ticker:
        raise RuntimeError("Environment variable 'TICKER' must not be empty.")
    return ticker


def _resolve_provider() -> str:
    """Read and validate the PROVIDER env var.

    Raises RuntimeError immediately if PROVIDER is absent or not a recognised
    value — fail-fast before any network I/O occurs.
    """
    raw = os.getenv("PROVIDER", "").strip().lower()
    if not raw:
        raise RuntimeError(
            "Required environment variable 'PROVIDER' is not set. "
            f"Must be one of: {', '.join(sorted(_VALID_PROVIDERS))}."
        )
    if raw not in _VALID_PROVIDERS:
        raise RuntimeError(
            f"Unknown PROVIDER '{raw}'. "
            f"Must be one of: {', '.join(sorted(_VALID_PROVIDERS))}."
        )
    return raw


def _validate_provider_secrets(provider: str) -> dict[str, str]:
    """Check that all secrets required by *provider* are present.

    Returns a mapping of secret env var name → value for use during ingestor
    construction. Raises RuntimeError on the first missing secret.
    """
    secrets: dict[str, str] = {}
    secret_var = _PROVIDER_REQUIRED_SECRETS.get(provider)
    if secret_var:
        value = os.getenv(secret_var, "").strip()
        if not value:
            raise RuntimeError(
                f"Provider '{provider}' requires environment variable '{secret_var}' "
                "but it is not set."
            )
        secrets[secret_var] = value
    return secrets


def _load_config() -> dict:
    provider = _resolve_provider()
    secrets = _validate_provider_secrets(provider)
    ticker = _load_ticker()

    lookback_minutes = int(os.getenv("NEWS_LOOKBACK_MINUTES", "60"))
    relevance_threshold = float(os.getenv("NEWS_RELEVANCE_THRESHOLD", "0.5"))
    dry_run = os.getenv("DRY_RUN", "false").lower() in ("1", "true", "yes")

    # RabbitMQ — required (skipped when dry_run=True).
    rabbitmq_host = os.getenv("RABBITMQ_HOST", "") if dry_run else _require_env("RABBITMQ_HOST")
    rabbitmq_port = int(os.getenv("RABBITMQ_PORT", "5672"))
    rabbitmq_queue = os.getenv("RABBITMQ_QUEUE", "raw-news")
    # Credentials injected from the operator-generated Secret in k8s;
    # default to guest/guest for local development only.
    rabbitmq_username = os.getenv("RABBITMQ_USERNAME", "guest")
    rabbitmq_password = os.getenv("RABBITMQ_PASSWORD", "guest")

    return {
        "provider": provider,
        "secrets": secrets,
        "ticker": ticker,
        "lookback_minutes": lookback_minutes,
        "relevance_threshold": relevance_threshold,
        "dry_run": dry_run,
        "rabbitmq_host": rabbitmq_host,
        "rabbitmq_port": rabbitmq_port,
        "rabbitmq_queue": rabbitmq_queue,
        "rabbitmq_username": rabbitmq_username,
        "rabbitmq_password": rabbitmq_password,
    }


# ---------------------------------------------------------------------------
# Ingestor factory
# ---------------------------------------------------------------------------


def _build_ingestor(config: dict) -> BaseIngestor:
    """Construct the single ingestor for the configured provider."""
    provider = config["provider"]
    secrets = config["secrets"]

    if provider == SourceProvider.ALPHA_VANTAGE:
        return AlphaVantageIngestor(api_key=secrets["ALPHA_VANTAGE_KEY"])

    if provider == SourceProvider.FINNHUB:
        return FinnhubIngestor(api_key=secrets["FINNHUB_API_KEY"])

    if provider == SourceProvider.YAHOO_RSS:
        return YahooFinanceIngestor()

    # Unreachable: _resolve_provider already validated the value.
    raise RuntimeError(f"No ingestor implementation for provider '{provider}'.")  # pragma: no cover


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def _publish_to_queue(items: list[NewsItem], config: dict) -> None:
    """Publish news items to the RabbitMQ raw-news queue."""
    publisher = RabbitMQPublisher(
        host=config["rabbitmq_host"],
        port=config["rabbitmq_port"],
        queue_name=config["rabbitmq_queue"],
        username=config["rabbitmq_username"],
        password=config["rabbitmq_password"],
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
    ingestor = _build_ingestor(config)
    logger.info("Provider: %s | Ticker: %s", config["provider"], config["ticker"])

    items = ingestor.fetch_news(
        ticker=config["ticker"],
        relevance_threshold=config["relevance_threshold"],
    )
    recent = filter_by_lookback(items, config["lookback_minutes"])
    logger.info(
        "[%s] %d items fetched, %d within lookback window.",
        ingestor.source_provider,
        len(items),
        len(recent),
    )

    if not recent:
        logger.info("No news items to process — pipeline complete.")
        return

    if config["dry_run"]:
        logger.info("[DRY RUN] Would publish %d items — skipping queue.", len(recent))
        return

    _publish_to_queue(recent, config)


def main() -> None:
    logger.info("Sentic-Signal pipeline starting.")
    config = _load_config()
    logger.info(
        "Provider: %s | Ticker: %s | Lookback: %d min | Queue: %s",
        config["provider"],
        config["ticker"],
        config["lookback_minutes"],
        config["rabbitmq_queue"],
    )
    run(config)
    logger.info("Pipeline complete.")


if __name__ == "__main__":
    main()
