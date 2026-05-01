"""Unit tests for the Yahoo Finance RSS ingestor module.

Covers the private helpers:
- _parse_raw_article()
- _extract_ticker_items()

The _fetch_news() function requires network access and is covered by
integration tests.
"""

import time
from datetime import UTC, datetime

import pytest

from sentic_signal.ingestor.yahoo_finance_rss import _extract_ticker_items, _parse_raw_article
from sentic_signal.models import SourceProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PUBLISHED_STRUCT = time.strptime("2026-04-13 14:30:45", "%Y-%m-%d %H:%M:%S")
_PUBLISHED_DT = datetime(2026, 4, 13, 14, 30, 45, tzinfo=UTC)

_MISSING = object()  # sentinel: caller explicitly omitted published_parsed


def _entry(
    title: str = "AAPL earnings beat expectations",
    link: str = "https://finance.yahoo.com/news/aapl-earnings",
    summary: str = "Apple Inc reported strong earnings.",
    published_parsed=_MISSING,
) -> dict:
    return {
        "title": title,
        "link": link,
        "summary": summary,
        "published_parsed": _PUBLISHED_STRUCT if published_parsed is _MISSING else published_parsed,
    }


# ---------------------------------------------------------------------------
# _parse_raw_article
# ---------------------------------------------------------------------------


class TestParseRawArticle:
    def test_parses_valid_entry(self) -> None:
        result = _parse_raw_article(_entry())
        assert result is not None
        headline, url, summary, published = result
        assert headline == "AAPL earnings beat expectations"
        assert url == "https://finance.yahoo.com/news/aapl-earnings"
        assert summary == "Apple Inc reported strong earnings."
        assert published == _PUBLISHED_DT

    def test_returns_none_when_published_parsed_missing(self) -> None:
        result = _parse_raw_article(_entry(published_parsed=None))
        # feedparser sets published_parsed=None when timestamp is absent
        assert result is None

    def test_returns_none_when_url_missing(self) -> None:
        result = _parse_raw_article(_entry(link=""))
        assert result is None

    def test_summary_is_none_when_absent(self) -> None:
        entry = _entry()
        entry["summary"] = None
        result = _parse_raw_article(entry)
        assert result is not None
        _, _, summary, _ = result
        assert summary is None

    def test_headline_can_be_empty_string(self) -> None:
        # headline is not a required field at parse stage; filtering is downstream
        result = _parse_raw_article(_entry(title=""))
        assert result is not None
        headline, _, _, _ = result
        assert headline == ""


# ---------------------------------------------------------------------------
# _extract_ticker_items
# ---------------------------------------------------------------------------


class TestExtractTickerItems:
    def _article(self, headline: str = "AAPL rises after earnings") -> tuple:
        return (headline, "https://finance.yahoo.com/news/aapl", "summary", _PUBLISHED_DT)

    def test_returns_item_when_ticker_in_headline(self) -> None:
        items = _extract_ticker_items(self._article("AAPL hits record high"), "AAPL", 0.5)
        assert len(items) == 1
        assert items[0].source_provider == SourceProvider.YAHOO_RSS
        assert items[0].ticker == "AAPL"

    def test_relevance_0_8_for_ticker_in_headline(self) -> None:
        # relevance_threshold=0.75 should still pass (0.8 >= 0.75)
        items = _extract_ticker_items(self._article("AAPL beats estimates"), "AAPL", 0.75)
        assert len(items) == 1

    def test_relevance_0_5_for_ticker_in_summary_only(self) -> None:
        article = ("Market outlook", "https://example.com", "AAPL shows strength", _PUBLISHED_DT)
        items = _extract_ticker_items(article, "AAPL", 0.4)
        assert len(items) == 1

    def test_returns_empty_when_relevance_below_threshold(self) -> None:
        # ticker not mentioned anywhere → relevance 0.1
        article = ("General market news", "https://example.com", "Markets fell today", _PUBLISHED_DT)
        items = _extract_ticker_items(article, "AAPL", 0.5)
        assert items == []

    def test_returns_empty_for_invalid_url(self) -> None:
        article = ("AAPL rally", "not-a-url", "AAPL up 5%", _PUBLISHED_DT)
        items = _extract_ticker_items(article, "AAPL", 0.5)
        assert items == []

    def test_ticker_match_is_case_insensitive(self) -> None:
        # headline uses lowercase ticker symbol
        items = _extract_ticker_items(self._article("aapl stock surges"), "AAPL", 0.5)
        assert len(items) == 1

    def test_source_provider_is_yahoo_rss(self) -> None:
        items = _extract_ticker_items(self._article("AAPL news"), "AAPL", 0.0)
        assert items[0].source_provider == SourceProvider.YAHOO_RSS
