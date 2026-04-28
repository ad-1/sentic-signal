"""Yahoo Finance RSS news provider adapter.

Implements the BaseIngestor protocol for Yahoo Finance RSS feeds.

Yahoo Finance RSS feeds are free with no rate limits, making them ideal for
high-frequency polling. They do not provide sentiment labels — the analyst
worker will populate sentic_sentiment for all items from this source.

Feed URL pattern: https://finance.yahoo.com/rss/2.0?ticker={ticker}

feedparser normalises publication timestamps to UTC in entry.published_parsed
(a time.struct_time), which is used in preference to raw string parsing.
"""

import logging
import time
from datetime import UTC, datetime

import feedparser
import requests

from sentic_signal.models import NewsItem, SentimentLabel

logger = logging.getLogger(__name__)

_YAHOO_RSS_ENDPOINT = "https://finance.yahoo.com/rss/2.0"
_REQUEST_TIMEOUT = 30  # seconds
_DEFAULT_RELEVANCE_THRESHOLD = 0.5
_SOURCE_PROVIDER = "yahoo_rss"


class YahooFinanceIngestor:
    """News provider adapter for Yahoo Finance RSS feeds."""

    source_provider: str = _SOURCE_PROVIDER

    def fetch_news(
        self,
        tickers: list[str],
        relevance_threshold: float = _DEFAULT_RELEVANCE_THRESHOLD,
    ) -> list[NewsItem]:
        """Fetch and normalise news for *tickers* from Yahoo Finance RSS.

        Args:
            tickers:             Uppercase ticker symbols (e.g. ["AAPL", "MSFT"]).
            relevance_threshold: Minimum relevance score to include.

        Returns:
            Normalised list of NewsItem objects.
        """
        return _fetch_news(tickers, relevance_threshold)


# ---------------------------------------------------------------------------
# Module-level implementation (private to this module)
# ---------------------------------------------------------------------------


def _fetch_news(
    tickers: list[str],
    relevance_threshold: float = _DEFAULT_RELEVANCE_THRESHOLD,
) -> list[NewsItem]:
    """Core Yahoo Finance RSS fetch logic."""
    tickers_upper = [t.upper() for t in tickers]
    items: list[NewsItem] = []

    for i, ticker in enumerate(tickers_upper):
        if i > 0:
            time.sleep(0.5)

        logger.info("Fetching news for ticker: %s", ticker)

        feed_url = f"{_YAHOO_RSS_ENDPOINT}?ticker={ticker}"

        try:
            response = requests.get(feed_url, timeout=_REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.error("Request failed for %s: %s", ticker, exc)
            continue

        feed = feedparser.parse(response.content)

        if not feed.entries:
            logger.info("No articles found for ticker %s.", ticker)
            continue

        logger.info("Received %d raw items for %s.", len(feed.entries), ticker)

        for entry in feed.entries:
            article = _parse_raw_article(entry)
            if article is None:
                continue
            items.extend(_extract_ticker_items(entry, article, [ticker], relevance_threshold))

    logger.info("%d items passed relevance filter for %s.", len(items), ",".join(tickers_upper))
    return items


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _parse_raw_article(entry) -> tuple[str, str, str, SentimentLabel | None, datetime] | None:
    """Parse and validate the shared fields of a raw RSS entry.

    Returns a tuple of (headline, url, summary, sentiment_label, published_dt)
    or None if any essential field is missing or unparseable.
    """
    headline = entry.get("title", "")
    url = entry.get("link", "")
    summary = entry.get("summary", "")

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

    # Yahoo Finance RSS provides no sentiment labels.
    return headline, url, summary, None, published_dt


def _extract_ticker_items(
    entry,
    article: tuple[str, str, str, SentimentLabel | None, datetime],
    tickers: list[str],
    relevance_threshold: float,
) -> list[NewsItem]:
    """Build a NewsItem for each ticker in *tickers* that passes the relevance filter.

    Since Yahoo Finance RSS does not supply ticker-level relevance scores,
    relevance is approximated via ticker mention in the headline and summary.
    """
    headline, url, summary, sentiment_label, published_dt = article
    items: list[NewsItem] = []

    article_text = f"{headline} {summary}".lower()

    for ticker in tickers:
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
            continue

        items.append(
            NewsItem(
                ticker=ticker,
                headline=headline,
                url=url,
                summary=summary,
                provider_sentiment=None,  # Yahoo RSS provides no sentiment.
                published=published_dt,
                relevance_score=relevance,
                source_provider=_SOURCE_PROVIDER,
            )
        )

    return items