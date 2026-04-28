"""Finnhub.io news provider adapter.

Implements the BaseIngestor protocol for the Finnhub Company News API.

Finnhub's /company-news endpoint returns articles for a single ticker over a
date range. The free tier allows 60 API requests per minute. Unlike Alpha
Vantage, Finnhub does not supply sentiment scores, so `provider_sentiment` is
always None. The `sentic_sentiment` field will be populated downstream by the
analyst worker.

Docs: https://finnhub.io/docs/api/company-news
"""

import logging
import time
from datetime import UTC, datetime, timedelta

import requests

from sentic_signal.models import NewsItem

logger = logging.getLogger(__name__)

_FINNHUB_ENDPOINT = "https://finnhub.io/api/v1/company-news"
_REQUEST_TIMEOUT = 15  # seconds
_INTER_REQUEST_DELAY = 1.1  # seconds — stay well under 60 req/min free limit
_SOURCE_PROVIDER = "finnhub"


class FinnhubIngestor:
    """News provider adapter for the Finnhub Company News API."""

    source_provider: str = _SOURCE_PROVIDER

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("Finnhub API key must not be empty.")
        self._api_key = api_key

    def fetch_news(
        self,
        tickers: list[str],
        relevance_threshold: float = 0.0,  # Finnhub has no relevance score; accept all
    ) -> list[NewsItem]:
        """Fetch and normalise news for *tickers* from Finnhub.

        Args:
            tickers:             Uppercase ticker symbols (e.g. ["AAPL", "MSFT"]).
            relevance_threshold: Ignored for Finnhub (no relevance scores supplied).
                                 Kept for interface compatibility.

        Returns:
            Normalised list of NewsItem objects.
        """
        return _fetch_news(tickers, self._api_key)


# ---------------------------------------------------------------------------
# Module-level implementation
# ---------------------------------------------------------------------------


def _fetch_news(tickers: list[str], api_key: str) -> list[NewsItem]:
    """Core Finnhub fetch logic — one request per ticker."""
    tickers_upper = [t.upper() for t in tickers]
    items: list[NewsItem] = []

    # Fetch the last 7 days. Lookback filtering to the configured window
    # is applied by the IngestorRunner (filter_by_lookback) after fetch.
    today = datetime.now(tz=UTC).date()
    from_date = (datetime.now(tz=UTC) - timedelta(days=7)).date()
    date_from = from_date.strftime("%Y-%m-%d")
    date_to = today.strftime("%Y-%m-%d")

    for i, ticker in enumerate(tickers_upper):
        if i > 0:
            time.sleep(_INTER_REQUEST_DELAY)

        logger.info("Fetching Finnhub news for ticker: %s (%s to %s)", ticker, date_from, date_to)

        params = {
            "symbol": ticker,
            "from": date_from,
            "to": date_to,
            "token": api_key.strip(),
        }

        try:
            response = requests.get(_FINNHUB_ENDPOINT, params=params, timeout=_REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.error("Finnhub request failed for %s: %s", ticker, exc)
            continue

        raw_articles: list[dict] = response.json()

        if not isinstance(raw_articles, list):
            logger.warning("Unexpected Finnhub response for %s: %s", ticker, raw_articles)
            continue

        logger.info("Received %d raw Finnhub items for %s.", len(raw_articles), ticker)

        for raw in raw_articles:
            item = _parse_article(raw, ticker)
            if item is not None:
                items.append(item)

    logger.info("%d Finnhub items fetched for %s.", len(items), ",".join(tickers_upper))
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
        published = datetime.fromtimestamp(int(unix_ts), tz=UTC)
    except (ValueError, OSError, OverflowError):
        logger.warning("Invalid Finnhub timestamp '%s' for article: %s", unix_ts, headline)
        return None

    return NewsItem(
        ticker=ticker,
        headline=headline,
        url=url,
        published=published,
        summary=(raw.get("summary") or "").strip(),
        source_provider=_SOURCE_PROVIDER,
        provider_sentiment=None,   # Finnhub does not supply sentiment
        sentic_sentiment=None,     # Populated by analyst worker
    )
