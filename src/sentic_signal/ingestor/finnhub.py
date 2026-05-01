"""Finnhub.io news provider adapter.

Implements the BaseIngestor protocol for the Finnhub Company News API.

Finnhub's /company-news endpoint returns articles for a single ticker over a
date range. The free tier allows 60 API requests per minute. Finnhub does not
supply sentiment scores, so `provider_sentiment` is always None for items from
this source. Sentiment analysis is performed downstream by the war room agents
in sentic-analyst.

Docs: https://finnhub.io/docs/api/company-news
"""

import logging
from datetime import UTC, datetime, timedelta

import requests
from pydantic import HttpUrl, TypeAdapter, ValidationError

from sentic_signal.models import NewsItem, SourceProvider

logger = logging.getLogger(__name__)

_FINNHUB_ENDPOINT = "https://finnhub.io/api/v1/company-news"
_REQUEST_TIMEOUT = 15  # seconds
_HTTP_URL_ADAPTER: TypeAdapter[HttpUrl] = TypeAdapter(HttpUrl)


class FinnhubIngestor:
    """News provider adapter for the Finnhub Company News API."""

    source_provider: SourceProvider = SourceProvider.FINNHUB

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("Finnhub API key must not be empty.")
        self._api_key = api_key

    def fetch_news(
        self,
        ticker: str,
        relevance_threshold: float = 0.0,  # Finnhub has no relevance score; accept all
    ) -> list[NewsItem]:
        """Fetch and normalise news for *ticker* from Finnhub.

        Args:
            ticker:              Uppercase ticker symbol (e.g. "AAPL").
            relevance_threshold: Ignored for Finnhub (no relevance scores supplied).
                                 Kept for interface compatibility.

        Returns:
            Normalised list of NewsItem objects.
        """
        return _fetch_news(ticker, self._api_key)


# ---------------------------------------------------------------------------
# Module-level implementation
# ---------------------------------------------------------------------------


def _fetch_news(ticker: str, api_key: str) -> list[NewsItem]:
    """Core Finnhub fetch logic for a single ticker."""
    ticker_upper = ticker.upper()
    items: list[NewsItem] = []

    # Fetch the last 7 days. Lookback filtering to the configured window
    # is applied by the IngestorRunner (filter_by_lookback) after fetch.
    today = datetime.now(tz=UTC).date()
    from_date = (datetime.now(tz=UTC) - timedelta(days=7)).date()
    date_from = from_date.strftime("%Y-%m-%d")
    date_to = today.strftime("%Y-%m-%d")

    logger.info("Fetching Finnhub news for ticker: %s (%s to %s)", ticker_upper, date_from, date_to)

    params = {
        "symbol": ticker_upper,
        "from": date_from,
        "to": date_to,
        "token": api_key.strip(),
    }

    try:
        response = requests.get(_FINNHUB_ENDPOINT, params=params, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        # Log only the exception type — the raw exception message may embed the
        # full request URL, which carries the API key as a query parameter.
        logger.error(
            "Finnhub request failed for %s (%s). Check FINNHUB_API_KEY and network.",
            ticker_upper,
            type(exc).__name__,
        )
        return []

    raw_articles: list[dict] = response.json()

    if not isinstance(raw_articles, list):
        logger.warning("Unexpected Finnhub response for %s: %s", ticker_upper, raw_articles)
        return []

    logger.info("Received %d raw Finnhub items for %s.", len(raw_articles), ticker_upper)

    for raw in raw_articles:
        item = _parse_article(raw, ticker_upper)
        if item is not None:
            items.append(item)

    logger.info("%d Finnhub items fetched for %s.", len(items), ticker_upper)
    return items


def _parse_article(raw: dict, ticker: str) -> NewsItem | None:
    """Parse a single Finnhub article dict into a NewsItem.

    Returns None and logs a warning if required fields are missing or invalid.
    """
    headline = (raw.get("headline") or "").strip()
    url = (raw.get("url") or "").strip()
    unix_ts = raw.get("datetime")

    if not headline or not url or not unix_ts:
        logger.debug("Skipping Finnhub article — missing required field: %s", raw)
        return None

    try:
        validated_url: HttpUrl = _HTTP_URL_ADAPTER.validate_python(url)
    except ValidationError:
        logger.warning("Invalid Finnhub URL for article: %r — skipping.", headline)
        return None

    try:
        published = datetime.fromtimestamp(int(unix_ts), tz=UTC)
    except (ValueError, OSError, OverflowError):
        logger.warning("Invalid Finnhub timestamp '%s' for article: %s", unix_ts, headline)
        return None

    return NewsItem(
        ticker=ticker,
        headline=headline,
        url=validated_url,
        published=published,
        summary=(raw.get("summary") or "").strip() or None,
        source_provider=SourceProvider.FINNHUB,
    )
