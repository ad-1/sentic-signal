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
import time
from datetime import UTC, datetime

import requests

from sentic_signal.models import NewsItem, SentimentLabel

logger = logging.getLogger(__name__)

_AV_ENDPOINT = "https://www.alphavantage.co/query"
_REQUEST_TIMEOUT = 30  # seconds
_DEFAULT_RELEVANCE_THRESHOLD = 0.5
_SOURCE_PROVIDER = "alpha_vantage"


class AlphaVantageIngestor:
    """News provider adapter for the Alpha Vantage NEWS_SENTIMENT API."""

    source_provider: str = _SOURCE_PROVIDER

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("Alpha Vantage API key must not be empty.")
        self._api_key = api_key

    def fetch_news(
        self,
        tickers: list[str],
        relevance_threshold: float = _DEFAULT_RELEVANCE_THRESHOLD,
    ) -> list[NewsItem]:
        """Fetch and normalise news for *tickers* from Alpha Vantage.

        Args:
            tickers:             Uppercase ticker symbols (e.g. ["AAPL", "MSFT"]).
            relevance_threshold: Minimum per-ticker relevance score to include.

        Returns:
            Normalised list of NewsItem objects.
        """
        return _fetch_news(tickers, self._api_key, relevance_threshold)


# ---------------------------------------------------------------------------
# Module-level implementation (used by the class; private to this module)
# ---------------------------------------------------------------------------


def _fetch_news(
    tickers: list[str],
    api_key: str,
    relevance_threshold: float = _DEFAULT_RELEVANCE_THRESHOLD,
) -> list[NewsItem]:
    """Core Alpha Vantage fetch logic."""
    tickers_upper = [t.upper() for t in tickers]
    items: list[NewsItem] = []

    for i, ticker in enumerate(tickers_upper):
        if i > 0:
            time.sleep(0.5)

        logger.info("Fetching news for ticker: %s", ticker)

        params = {
            "function": "NEWS_SENTIMENT",
            "tickers": ticker,
            "apikey": api_key.strip(),
            "limit": 50,
            "sort": "LATEST",
        }

        try:
            response = requests.get(_AV_ENDPOINT, params=params, timeout=_REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.error("Request failed for %s: %s", ticker, exc)
            continue

        data = response.json()

        # Alpha Vantage signals rate-limit exhaustion via JSON fields, not HTTP codes.
        if "Note" in data:
            logger.warning("Alpha Vantage rate limit hit for %s: %s", ticker, data["Note"])
            break
        if "Information" in data:
            logger.warning("Alpha Vantage info message for %s: %s", ticker, data["Information"])
            continue

        raw_feed: list[dict] = data.get("feed", [])
        logger.info("Received %d raw items for %s.", len(raw_feed), ticker)

        for raw in raw_feed:
            article = _parse_raw_article(raw)
            if article is None:
                continue
            items.extend(_extract_ticker_items(raw, article, [ticker], relevance_threshold))

    logger.info("%d items passed relevance filter for %s.", len(items), ",".join(tickers_upper))
    return items


# ---------------------------------------------------------------------------
# Private helpers (imported directly by unit tests)
# ---------------------------------------------------------------------------


def _parse_raw_article(raw: dict) -> tuple[str, str, str, SentimentLabel | None, datetime] | None:
    """Parse and validate the shared fields of a raw article dictionary.

    Returns a tuple of (headline, url, summary, sentiment_label, published_dt)
    or None if any essential field is missing or unparseable.
    """
    headline = raw.get("title", "")
    url = raw.get("url", "")
    summary = raw.get("summary", "")
    sentiment_label = _parse_sentiment(raw.get("overall_sentiment_label"))
    published_dt = _parse_timestamp(raw.get("time_published", ""))

    if published_dt is None:
        logger.warning("Unparseable time_published: %r — skipping.", raw.get("time_published"))
        return None

    if not url:
        logger.warning("Missing URL for article: %r — skipping.", headline)
        return None

    return headline, url, summary, sentiment_label, published_dt


def _extract_ticker_items(
    raw: dict,
    article: tuple[str, str, str, SentimentLabel | None, datetime],
    tickers: list[str],
    relevance_threshold: float,
) -> list[NewsItem]:
    """Build a NewsItem for each ticker in *tickers* that passes the relevance filter.

    Args:
        raw:                 The raw article dict (used to read ticker_sentiment).
        article:             Pre-parsed (headline, url, summary, sentiment, published) tuple.
        tickers:             Uppercase ticker symbols to match against.
        relevance_threshold: Minimum relevance score to include.

    Returns:
        A (possibly empty) list of NewsItem objects — one per matching ticker.
    """
    headline, url, summary, sentiment_label, published_dt = article
    ticker_set = set(tickers)
    items: list[NewsItem] = []

    for ts in raw.get("ticker_sentiment", []):
        single_ticker = ts.get("ticker", "").upper()
        if single_ticker not in ticker_set:
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

        items.append(
            NewsItem(
                ticker=single_ticker,
                headline=headline,
                url=url,
                summary=summary,
                provider_sentiment=sentiment_label,
                published=published_dt,
                relevance_score=relevance,
                source_provider=_SOURCE_PROVIDER,
            )
        )

    return items


def _parse_timestamp(value: str) -> datetime | None:
    """Parse Alpha Vantage's compact timestamp format (YYYYMMDDTHHMMSS)."""
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def _parse_sentiment(label: str | None) -> SentimentLabel | None:
    """Safely coerce raw AV sentiment string to SentimentLabel enum."""
    if label is None:
        return None
    try:
        return SentimentLabel(label)
    except ValueError:
        logger.debug("Unknown sentiment label: %r", label)
        return None
