"""Sentic-Signal ingestor package.

Defines the BaseIngestor protocol that all news provider adapters must implement,
and shared utilities used across ingestors.
"""

from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

from sentic_signal.models import NewsItem, SourceProvider


@runtime_checkable
class BaseIngestor(Protocol):
    """Standard interface all news provider adapters must implement.

    Every ingestor fetches news from its source, normalises it into
    NewsItem objects, and returns them. The pipeline is coded against
    this protocol — not any specific provider implementation.
    """

    source_provider: SourceProvider

    def fetch_news(
        self,
        ticker: str,
        relevance_threshold: float = 0.5,
    ) -> list[NewsItem]:
        """Fetch and normalise news for the given ticker.

        Args:
            ticker:              Uppercase ticker symbol (e.g. "AAPL").
            relevance_threshold: Minimum relevance score (0–1) to include an article.

        Returns:
            Normalised list of NewsItem objects ready for the raw-news queue.
        """
        ...


def filter_by_lookback(items: list[NewsItem], lookback_minutes: int) -> list[NewsItem]:
    """Filter news items to only those published within the last *lookback_minutes*.

    Args:
        items:            List of NewsItem objects to filter.
        lookback_minutes: Maximum article age in minutes.

    Returns:
        Filtered list of NewsItem objects within the lookback window.
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(minutes=lookback_minutes)
    return [item for item in items if item.published >= cutoff]
