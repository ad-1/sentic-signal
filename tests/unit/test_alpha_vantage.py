"""Unit tests for the Alpha Vantage ingestor module.

These tests cover the private helper functions:
- _parse_timestamp()
- _parse_sentiment()
- _parse_raw_article()
- _extract_ticker_items()
"""

from datetime import UTC, datetime
from unittest.mock import patch
import pytest

from sentic_signal.ingestor.alpha_vantage import (
    _parse_timestamp,
    _parse_sentiment,
    _parse_raw_article,
    _extract_ticker_items,
)
from sentic_signal.models import NewsItem, SentimentLabel


# ---------------------------------------------------------------------------
# _parse_timestamp tests
# ---------------------------------------------------------------------------


class TestParseTimestamp:
    def test_parses_valid_timestamp(self) -> None:
        """Test parsing a valid timestamp string."""
        result = _parse_timestamp("20260413T143045")
        expected = datetime(2026, 4, 13, 14, 30, 45, tzinfo=UTC)
        assert result == expected

    def test_returns_none_for_invalid_timestamp(self) -> None:
        """Test that invalid timestamp strings return None."""
        result = _parse_timestamp("invalid")
        assert result is None

    def test_returns_none_for_empty_string(self) -> None:
        """Test that empty timestamp strings return None."""
        result = _parse_timestamp("")
        assert result is None

    def test_handles_various_timestamp_formats(self) -> None:
        """Test parsing various valid timestamp formats."""
        test_cases = [
            ("20260101T000000", datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)),
            ("20261231T235959", datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC)),
        ]
        
        for timestamp_str, expected in test_cases:
            result = _parse_timestamp(timestamp_str)
            assert result == expected


# ---------------------------------------------------------------------------
# _parse_sentiment tests
# ---------------------------------------------------------------------------


class TestParseSentiment:
    def test_parses_valid_sentiment_labels(self) -> None:
        """Test parsing valid sentiment labels."""
        test_cases = [
            ("Bullish", SentimentLabel.BULLISH),
            ("Somewhat-Bullish", SentimentLabel.SOMEWHAT_BULLISH),
            ("Neutral", SentimentLabel.NEUTRAL),
            ("Somewhat-Bearish", SentimentLabel.SOMEWHAT_BEARISH),
            ("Bearish", SentimentLabel.BEARISH),
        ]
        
        for label, expected in test_cases:
            result = _parse_sentiment(label)
            assert result == expected

    def test_returns_none_for_invalid_sentiment(self) -> None:
        """Test that invalid sentiment labels return None."""
        result = _parse_sentiment("Invalid")
        assert result is None

    def test_returns_none_for_none_input(self) -> None:
        """Test that None input returns None."""
        result = _parse_sentiment(None)
        assert result is None

    def test_handles_special_characters_in_labels(self) -> None:
        """Test handling of labels with special characters."""
        result = _parse_sentiment("Somewhat-Bullish")
        assert result == SentimentLabel.SOMEWHAT_BULLISH


# ---------------------------------------------------------------------------
# _parse_raw_article tests
# ---------------------------------------------------------------------------


class TestParseRawArticle:
    def test_parses_valid_article(self) -> None:
        """Test parsing a valid raw article dictionary."""
        raw_article = {
            "title": "Test headline",
            "url": "https://example.com/test",
            "summary": "Test summary",
            "time_published": "20260413T143045",
            "overall_sentiment_label": "Bullish",
        }
        
        result = _parse_raw_article(raw_article)
        expected = (
            "Test headline",
            "https://example.com/test",
            "Test summary",
            SentimentLabel.BULLISH,
            datetime(2026, 4, 13, 14, 30, 45, tzinfo=UTC)
        )
        assert result == expected

    def test_returns_none_for_missing_url(self) -> None:
        """Test that articles with missing URL return None."""
        raw_article = {
            "title": "Test headline",
            "url": "",  # Empty URL
            "summary": "Test summary",
            "time_published": "20260413T143045",
            "overall_sentiment_label": "Bullish",
        }
        
        result = _parse_raw_article(raw_article)
        assert result is None

    def test_returns_none_for_unparseable_timestamp(self) -> None:
        """Test that articles with unparseable timestamp return None."""
        raw_article = {
            "title": "Test headline",
            "url": "https://example.com/test",
            "summary": "Test summary",
            "time_published": "invalid_timestamp",
            "overall_sentiment_label": "Bullish",
        }
        
        result = _parse_raw_article(raw_article)
        assert result is None

    def test_handles_missing_fields_gracefully(self) -> None:
        """Test handling of missing fields in raw article."""
        raw_article = {
            "title": "Test headline",
            # Missing url, summary, time_published, overall_sentiment_label
        }
        
        result = _parse_raw_article(raw_article)
        assert result is None

    def test_handles_none_sentiment_label(self) -> None:
        """Test handling of None sentiment label."""
        raw_article = {
            "title": "Test headline",
            "url": "https://example.com/test",
            "summary": "Test summary",
            "time_published": "20260413T143045",
            "overall_sentiment_label": None,
        }
        
        result = _parse_raw_article(raw_article)
        expected = (
            "Test headline",
            "https://example.com/test",
            "Test summary",
            None,
            datetime(2026, 4, 13, 14, 30, 45, tzinfo=UTC)
        )
        assert result == expected


# ---------------------------------------------------------------------------
# _extract_ticker_items tests
# ---------------------------------------------------------------------------


class TestExtractTickerItems:
    def test_extracts_items_with_valid_relevance(self) -> None:
        """Test extracting items when relevance threshold is met."""
        raw_article = {
            "ticker_sentiment": [
                {
                    "ticker": "AAPL",
                    "relevance_score": 0.7,
                }
            ]
        }
        
        article = (
            "Test headline",
            "https://example.com/test",
            "Test summary",
            SentimentLabel.BULLISH,
            datetime(2026, 4, 13, 14, 30, 45, tzinfo=UTC)
        )
        
        result = _extract_ticker_items(raw_article, article, ["AAPL"], 0.5)
        assert len(result) == 1
        assert result[0].ticker == "AAPL"
        assert result[0].headline == "Test headline"
        assert str(result[0].url) == "https://example.com/test"
        assert result[0].summary == "Test summary"
        assert result[0].provider_sentiment == SentimentLabel.BULLISH
        assert result[0].published == datetime(2026, 4, 13, 14, 30, 45, tzinfo=UTC)
        assert result[0].relevance_score == 0.7

    def test_skips_items_below_relevance_threshold(self) -> None:
        """Test that items below the relevance threshold are skipped."""
        raw_article = {
            "ticker_sentiment": [
                {
                    "ticker": "AAPL",
                    "relevance_score": 0.3,  # Below threshold of 0.5
                }
            ]
        }
        
        article = (
            "Test headline",
            "https://example.com/test",
            "Test summary",
            SentimentLabel.BULLISH,
            datetime(2026, 4, 13, 14, 30, 45, tzinfo=UTC)
        )
        
        result = _extract_ticker_items(raw_article, article, ["AAPL"], 0.5)
        assert len(result) == 0

    def test_skips_items_for_non_matching_ticker(self) -> None:
        """Test that items for non-matching tickers are skipped."""
        raw_article = {
            "ticker_sentiment": [
                {
                    "ticker": "MSFT",  # Different ticker
                    "relevance_score": 0.7,
                }
            ]
        }
        
        article = (
            "Test headline",
            "https://example.com/test",
            "Test summary",
            SentimentLabel.BULLISH,
            datetime(2026, 4, 13, 14, 30, 45, tzinfo=UTC)
        )
        
        result = _extract_ticker_items(raw_article, article, ["AAPL"], 0.5)
        assert len(result) == 0

    def test_handles_invalid_relevance_score(self) -> None:
        """Test handling of invalid relevance scores."""
        raw_article = {
            "ticker_sentiment": [
                {
                    "ticker": "AAPL",
                    "relevance_score": "invalid",  # Invalid score
                }
            ]
        }
        
        article = (
            "Test headline",
            "https://example.com/test",
            "Test summary",
            SentimentLabel.BULLISH,
            datetime(2026, 4, 13, 14, 30, 45, tzinfo=UTC)
        )
        
        result = _extract_ticker_items(raw_article, article, ["AAPL"], 0.5)
        assert len(result) == 0  # Should skip due to invalid score

    def test_handles_multiple_matching_tickers(self) -> None:
        """Test handling of multiple tickers in the same article."""
        raw_article = {
            "ticker_sentiment": [
                {
                    "ticker": "AAPL",
                    "relevance_score": 0.7,
                },
                {
                    "ticker": "MSFT",
                    "relevance_score": 0.8,
                }
            ]
        }
        
        article = (
            "Test headline",
            "https://example.com/test",
            "Test summary",
            SentimentLabel.BULLISH,
            datetime(2026, 4, 13, 14, 30, 45, tzinfo=UTC)
        )
        
        result = _extract_ticker_items(raw_article, article, ["AAPL", "MSFT"], 0.5)
        assert len(result) == 2
        assert result[0].ticker == "AAPL"
        assert result[1].ticker == "MSFT"

    def test_handles_empty_ticker_sentiment(self) -> None:
        """Test handling of empty ticker_sentiment list."""
        raw_article = {
            "ticker_sentiment": []
        }
        
        article = (
            "Test headline",
            "https://example.com/test",
            "Test summary",
            SentimentLabel.BULLISH,
            datetime(2026, 4, 13, 14, 30, 45, tzinfo=UTC)
        )
        
        result = _extract_ticker_items(raw_article, article, ["AAPL"], 0.5)
        assert len(result) == 0

    def test_handles_missing_ticker_sentiment(self) -> None:
        """Test handling of missing ticker_sentiment field."""
        raw_article = {
            # No ticker_sentiment key
        }
        
        article = (
            "Test headline",
            "https://example.com/test",
            "Test summary",
            SentimentLabel.BULLISH,
            datetime(2026, 4, 13, 14, 30, 45, tzinfo=UTC)
        )
        
        result = _extract_ticker_items(raw_article, article, ["AAPL"], 0.5)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Integration tests for the complete flow
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_full_flow_with_valid_data(self) -> None:
        """Test the full flow with valid data (this would require mocking the API)."""
        # This test would require mocking requests.get and the API response
        # For now, we'll just verify the function signatures work correctly
        pass