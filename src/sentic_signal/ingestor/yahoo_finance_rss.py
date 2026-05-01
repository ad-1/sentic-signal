"""Yahoo Finance RSS news provider adapter.

Implements the BaseIngestor protocol for Yahoo Finance RSS feeds.

Yahoo Finance RSS feeds are free and require no API key. However, Yahoo does
apply IP-level rate limiting on burst traffic — rapid successive requests
(e.g. dense manual testing) will produce HTTP 429 responses. At the default
CronJob schedule (every 2 hours) this is not a production concern. The fetcher
makes a single HTTP request per run regardless of lookback window size; lookback
is a client-side filter applied after the response is received.

Yahoo does not provide sentiment labels, so `provider_sentiment` is always None
for items from this source. Sentiment analysis is performed downstream by the
war room agents in sentic-analyst.

Feed URL pattern: https://finance.yahoo.com/rss/2.0?ticker={ticker}

feedparser normalises publication timestamps to UTC in entry.published_parsed
(a time.struct_time), which is used in preference to raw string parsing.
"""

import logging
from datetime import UTC, datetime

import feedparser
import requests
from pydantic import HttpUrl, TypeAdapter, ValidationError

from sentic_signal.models import NewsItem, SourceProvider

logger = logging.getLogger(__name__)

_YAHOO_RSS_ENDPOINT = "https://finance.yahoo.com/rss/2.0"
_REQUEST_TIMEOUT = 30  # seconds
_DEFAULT_RELEVANCE_THRESHOLD = 0.5
_HTTP_URL_ADAPTER: TypeAdapter[HttpUrl] = TypeAdapter(HttpUrl)


class YahooFinanceIngestor:
    """News provider adapter for Yahoo Finance RSS feeds."""

    source_provider: SourceProvider = SourceProvider.YAHOO_RSS

    def fetch_news(
        self,
        ticker: str,
        relevance_threshold: float = _DEFAULT_RELEVANCE_THRESHOLD,
    ) -> list[NewsItem]:
        """Fetch and normalise news for *ticker* from Yahoo Finance RSS.

        Args:
            ticker:              Uppercase ticker symbol (e.g. "AAPL").
            relevance_threshold: Minimum relevance score to include.

        Returns:
            Normalised list of NewsItem objects.
        """
        return _fetch_news(ticker, relevance_threshold)


# ---------------------------------------------------------------------------
# Module-level implementation (private to this module)
# ---------------------------------------------------------------------------


def _fetch_news(
    ticker: str,
    relevance_threshold: float = _DEFAULT_RELEVANCE_THRESHOLD,
) -> list[NewsItem]:
    """Core Yahoo Finance RSS fetch logic."""
    ticker_upper = ticker.upper()
    items: list[NewsItem] = []

    logger.info("Fetching news for ticker: %s", ticker_upper)

    feed_url = f"{_YAHOO_RSS_ENDPOINT}?ticker={ticker_upper}"

    try:
        response = requests.get(feed_url, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Request failed for %s: %s", ticker_upper, exc)
        return []

    feed = feedparser.parse(response.content)

    if not feed.entries:
        logger.info("No articles found for ticker %s.", ticker_upper)
        return []

    logger.info("Received %d raw items for %s.", len(feed.entries), ticker_upper)

    for entry in feed.entries:
        article = _parse_raw_article(entry)
        if article is None:
            continue
        items.extend(_extract_ticker_items(article, ticker_upper, relevance_threshold))

    logger.info("%d items passed relevance filter for %s.", len(items), ticker_upper)
    return items


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _parse_raw_article(entry) -> tuple[str, str, str | None, datetime] | None:
    """Parse and validate the shared fields of a raw RSS entry.

    Returns a tuple of (headline, url, summary, published_dt)
    or None if any essential field is missing or unparseable.
    """
    headline = entry.get("title", "")
    url = entry.get("link", "")
    summary = entry.get("summary") or None

    # feedparser normalises timestamps to UTC in entry.published_parsed.
    published_parsed = entry.get("published_parsed")
    if published_parsed:
        published_dt = datetime(*published_parsed[:6], tzinfo=UTC)
    else:
        logger.warning("Missing published timestamp for article: %r — skipping.", headline)
        return None

    if not url:
        logger.warning("Missing URL for article: %r — skipping.", headline)
        return None

    return headline, url, summary, published_dt


def _extract_ticker_items(
    article: tuple[str, str, str | None, datetime],
    ticker: str,
    relevance_threshold: float,
) -> list[NewsItem]:
    """Build a NewsItem for *ticker* when it passes the relevance filter.

    Since Yahoo Finance RSS does not supply ticker-level relevance scores,
    relevance is approximated via ticker mention in the headline and summary.
    """
    headline, url, summary, published_dt = article
    items: list[NewsItem] = []

    try:
        validated_url: HttpUrl = _HTTP_URL_ADAPTER.validate_python(url)
    except ValidationError:
        logger.warning("Invalid URL for article: %r — skipping.", headline)
        return []

    article_text = f"{headline} {summary or ''}".lower()
    ticker_lower = ticker.lower()

    if ticker_lower in headline.lower():
        relevance = 0.8
    elif ticker_lower in article_text:
        relevance = 0.5
    else:
        relevance = 0.1

    if relevance < relevance_threshold:
        logger.debug(
            "Skipping low-relevance article (%.2f) for %s: %s",
            relevance, ticker, headline,
        )
        return []

    items.append(
        NewsItem(
            ticker=ticker,
            headline=headline,
            url=validated_url,
            summary=summary,
            published=published_dt,
            source_provider=SourceProvider.YAHOO_RSS,
        )
    )

    return items