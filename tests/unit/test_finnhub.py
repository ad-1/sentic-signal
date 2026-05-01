"""Unit tests for the Finnhub ingestor module.

Covers the private helpers:
- _parse_article()

The _fetch_news() function requires network access and is covered by
integration tests.
"""

import time
from datetime import UTC, datetime

import pytest

from sentic_signal.ingestor.finnhub import _parse_article
from sentic_signal.models import SourceProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_UNIX_TS = int(datetime(2026, 4, 13, 14, 30, 45, tzinfo=UTC).timestamp())


def _raw(
    headline: str = "Stock hits all-time high",
    url: str = "https://example.com/article",
    unix_ts: int | None = None,
    summary: str = "A brief summary.",
) -> dict:
    return {
        "headline": headline,
        "url": url,
        "datetime": unix_ts if unix_ts is not None else _VALID_UNIX_TS,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# _parse_article
# ---------------------------------------------------------------------------


class TestParseArticle:
    def test_parses_valid_article(self) -> None:
        result = _parse_article(_raw(), ticker="AAPL")
        assert result is not None
        assert result.headline == "Stock hits all-time high"
        assert result.ticker == "AAPL"
        assert result.source_provider == SourceProvider.FINNHUB
        assert result.published == datetime.fromtimestamp(_VALID_UNIX_TS, tz=UTC)

    def test_returns_none_for_missing_headline(self) -> None:
        result = _parse_article(_raw(headline=""), ticker="AAPL")
        assert result is None

    def test_returns_none_for_missing_url(self) -> None:
        result = _parse_article(_raw(url=""), ticker="AAPL")
        assert result is None

    def test_returns_none_for_missing_timestamp(self) -> None:
        raw = _raw()
        del raw["datetime"]
        result = _parse_article(raw, ticker="AAPL")
        assert result is None

    def test_returns_none_for_invalid_url(self) -> None:
        result = _parse_article(_raw(url="not-a-url"), ticker="AAPL")
        assert result is None

    def test_returns_none_for_invalid_timestamp(self) -> None:
        result = _parse_article(_raw(unix_ts=-99999999999), ticker="AAPL")
        assert result is None

    def test_summary_is_none_when_empty(self) -> None:
        result = _parse_article(_raw(summary=""), ticker="AAPL")
        assert result is not None
        assert result.summary is None

    def test_summary_populated_when_present(self) -> None:
        result = _parse_article(_raw(summary="Summary text."), ticker="AAPL")
        assert result is not None
        assert result.summary == "Summary text."

    def test_ticker_is_stored_on_result(self) -> None:
        result = _parse_article(_raw(), ticker="TSLA")
        assert result is not None
        assert result.ticker == "TSLA"

    def test_url_is_preserved(self) -> None:
        result = _parse_article(_raw(url="https://finance.yahoo.com/news/story"), ticker="AAPL")
        assert result is not None
        assert str(result.url).startswith("https://finance.yahoo.com/news/story")
