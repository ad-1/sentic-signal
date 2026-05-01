"""Alpha Vantage news provider adapter.

Implements the BaseIngestor protocol for the Alpha Vantage NEWS_SENTIMENT API.

Alpha Vantage's NEWS_SENTIMENT endpoint returns articles with per-ticker
relevance scores and overall sentiment labels. Rate limits on the free tier
are strict (25 req/day) — the ingestor should be scheduled infrequently
(e.g. every 2 hours via a Kubernetes CronJob).

Rate-limit signals are returned as JSON "Note" / "Information" fields rather
than HTTP errors and are handled gracefully.
"""

import logging
from datetime import UTC, datetime

import requests
from pydantic import HttpUrl, TypeAdapter, ValidationError

from sentic_signal.models import NewsItem, SourceProvider

logger = logging.getLogger(__name__)

_AV_ENDPOINT = "https://www.alphavantage.co/query"
_REQUEST_TIMEOUT = 30  # seconds
_DEFAULT_RELEVANCE_THRESHOLD = 0.5
_HTTP_URL_ADAPTER: TypeAdapter[HttpUrl] = TypeAdapter(HttpUrl)


class AlphaVantageIngestor:
    """News provider adapter for the Alpha Vantage NEWS_SENTIMENT API."""

    source_provider: SourceProvider = SourceProvider.ALPHA_VANTAGE

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("Alpha Vantage API key must not be empty.")
        self._api_key = api_key

    def fetch_news(
        self,
        ticker: str,
        relevance_threshold: float = _DEFAULT_RELEVANCE_THRESHOLD,
    ) -> list[NewsItem]:
        """Fetch and normalise news for *ticker* from Alpha Vantage.

        Args:
            ticker:              Uppercase ticker symbol (e.g. "AAPL").
            relevance_threshold: Minimum per-ticker relevance score to include.

        Returns:
            Normalised list of NewsItem objects.
        """
        return _fetch_news(ticker, self._api_key, relevance_threshold)


# ---------------------------------------------------------------------------
# Module-level implementation (used by the class; private to this module)
# ---------------------------------------------------------------------------


def _fetch_news(
    ticker: str,
    api_key: str,
    relevance_threshold: float = _DEFAULT_RELEVANCE_THRESHOLD,
) -> list[NewsItem]:
    """Core Alpha Vantage fetch logic."""
    ticker_upper = ticker.upper()
    items: list[NewsItem] = []

    logger.info("Fetching news for ticker: %s", ticker_upper)

    params = {
        "function": "NEWS_SENTIMENT",
        "tickers": ticker_upper,
        "apikey": api_key.strip(),
        "limit": 50,
        "sort": "LATEST",
    }

    try:
        response = requests.get(_AV_ENDPOINT, params=params, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        # Log only the exception type — the raw exception message may embed the
        # full request URL, which carries the API key as a query parameter.
        logger.error(
            "Alpha Vantage request failed for %s (%s). Check ALPHA_VANTAGE_KEY and network.",
            ticker_upper,
            type(exc).__name__,
        )
        return []

    data = response.json()

    # Alpha Vantage signals rate-limit exhaustion via JSON fields, not HTTP codes.
    if "Note" in data:
        logger.warning("Alpha Vantage rate limit hit for %s: %s", ticker_upper, data["Note"])
        return []
    if "Information" in data:
        logger.warning("Alpha Vantage info message for %s: %s", ticker_upper, data["Information"])
        return []

    raw_feed: list[dict] = data.get("feed", [])
    logger.info("Received %d raw items for %s.", len(raw_feed), ticker_upper)

    for raw in raw_feed:
        article = _parse_raw_article(raw)
        if article is None:
            continue
        items.extend(_extract_ticker_items(raw, article, ticker_upper, relevance_threshold))

    logger.info("%d items passed relevance filter for %s.", len(items), ticker_upper)
    return items


# ---------------------------------------------------------------------------
# Private helpers (imported directly by unit tests)
# ---------------------------------------------------------------------------


def _parse_raw_article(raw: dict) -> tuple[str, str, str | None, datetime] | None:
    """Parse and validate the shared fields of a raw article dictionary.

    Returns a tuple of (headline, url, summary, published_dt)
    or None if any essential field is missing or unparseable.
    """
    headline = raw.get("title", "")
    url = raw.get("url", "")
    summary = raw.get("summary") or None
    published_dt = _parse_timestamp(raw.get("time_published", ""))

    if published_dt is None:
        logger.warning("Unparseable time_published: %r — skipping.", raw.get("time_published"))
        return None

    if not url:
        logger.warning("Missing URL for article: %r — skipping.", headline)
        return None

    return headline, url, summary, published_dt


def _extract_ticker_items(
    raw: dict,
    article: tuple[str, str, str | None, datetime],
    ticker: str,
    relevance_threshold: float,
) -> list[NewsItem]:
    """Build a NewsItem for *ticker* when it passes the relevance filter.

    Args:
        raw:                 The raw article dict (used to read ticker_sentiment
                             and article-level metadata).
        article:             Pre-parsed (headline, url, summary, published) tuple.
        ticker:              Uppercase ticker symbol to match against.
        relevance_threshold: Minimum relevance score to include.

    Returns:
        A (possibly empty) list of NewsItem objects for the target ticker.
    """
    headline, url, summary, published_dt = article
    items: list[NewsItem] = []

    try:
        validated_url: HttpUrl = _HTTP_URL_ADAPTER.validate_python(url)
    except ValidationError:
        logger.warning("Invalid URL for article: %r — skipping.", headline)
        return []

    # Article-level metadata — logged for observability but not included in the
    # NewsItem contract (AV-specific fields that don't generalise across providers).
    source: str | None = raw.get("source") or None
    source_domain: str | None = raw.get("source_domain") or None
    authors: list[str] = raw.get("authors") or []
    topics: list[str] = [t["topic"] for t in raw.get("topics", []) if t.get("topic")]

    for ts in raw.get("ticker_sentiment", []):
        single_ticker = ts.get("ticker", "").upper()
        if single_ticker != ticker:
            continue

        try:
            relevance = float(ts.get("relevance_score", 0.0))
        except (TypeError, ValueError):
            relevance = 0.0

        if relevance < relevance_threshold:
            logger.debug(
                "Skipping low-relevance article (%.2f) for %s: %s",
                relevance, single_ticker, headline,
            )
            continue

        logger.debug(
            "Article metadata — source: %r, domain: %r, authors: %r, topics: %r",
            source, source_domain, authors, topics,
        )
        items.append(
            NewsItem(
                ticker=single_ticker,
                headline=headline,
                url=validated_url,
                summary=summary,
                published=published_dt,
                source_provider=SourceProvider.ALPHA_VANTAGE,
            )
        )

    return items


def _parse_timestamp(value: str) -> datetime | None:
    """Parse Alpha Vantage's compact timestamp format (YYYYMMDDTHHMMSS)."""
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None
