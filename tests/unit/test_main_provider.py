"""Unit tests for the PROVIDER runtime contract in main.py.

Covers:
- _resolve_provider: valid values, missing env var, unrecognised value.
- _validate_provider_secrets: present secrets pass, missing secrets fail.
- _build_ingestor: correct ingestor type instantiated per provider.
- run(): dry-run short-circuits queue dispatch.
"""

import pytest

import sentic_signal.main as main_module
from sentic_signal.ingestor.alpha_vantage import AlphaVantageIngestor
from sentic_signal.ingestor.finnhub import FinnhubIngestor
from sentic_signal.ingestor.yahoo_finance_rss import YahooFinanceIngestor
from sentic_signal.models import SourceProvider


# ---------------------------------------------------------------------------
# _resolve_provider
# ---------------------------------------------------------------------------


class TestResolveProvider:
    def test_returns_alpha_vantage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROVIDER", "alpha_vantage")
        assert main_module._resolve_provider() == "alpha_vantage"

    def test_returns_finnhub(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROVIDER", "finnhub")
        assert main_module._resolve_provider() == "finnhub"

    def test_returns_yahoo_rss(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROVIDER", "yahoo_rss")
        assert main_module._resolve_provider() == "yahoo_rss"

    def test_strips_whitespace_and_lowercases(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROVIDER", "  FINNHUB  ")
        assert main_module._resolve_provider() == "finnhub"

    def test_raises_when_provider_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PROVIDER", raising=False)
        with pytest.raises(RuntimeError, match="PROVIDER"):
            main_module._resolve_provider()

    def test_raises_when_provider_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROVIDER", "")
        with pytest.raises(RuntimeError, match="PROVIDER"):
            main_module._resolve_provider()

    def test_raises_for_unknown_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROVIDER", "bloomberg")
        with pytest.raises(RuntimeError, match="bloomberg"):
            main_module._resolve_provider()

    def test_error_message_lists_valid_providers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROVIDER", "unknown")
        with pytest.raises(RuntimeError, match="alpha_vantage"):
            main_module._resolve_provider()


# ---------------------------------------------------------------------------
# _validate_provider_secrets
# ---------------------------------------------------------------------------


class TestValidateProviderSecrets:
    def test_alpha_vantage_passes_with_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALPHA_VANTAGE_KEY", "test-key-123")
        secrets = main_module._validate_provider_secrets(SourceProvider.ALPHA_VANTAGE)
        assert secrets["ALPHA_VANTAGE_KEY"] == "test-key-123"

    def test_alpha_vantage_raises_without_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ALPHA_VANTAGE_KEY", raising=False)
        with pytest.raises(RuntimeError, match="ALPHA_VANTAGE_KEY"):
            main_module._validate_provider_secrets(SourceProvider.ALPHA_VANTAGE)

    def test_alpha_vantage_raises_when_key_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALPHA_VANTAGE_KEY", "")
        with pytest.raises(RuntimeError, match="ALPHA_VANTAGE_KEY"):
            main_module._validate_provider_secrets(SourceProvider.ALPHA_VANTAGE)

    def test_finnhub_passes_with_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FINNHUB_API_KEY", "finn-key-456")
        secrets = main_module._validate_provider_secrets(SourceProvider.FINNHUB)
        assert secrets["FINNHUB_API_KEY"] == "finn-key-456"

    def test_finnhub_raises_without_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="FINNHUB_API_KEY"):
            main_module._validate_provider_secrets(SourceProvider.FINNHUB)

    def test_yahoo_rss_requires_no_secrets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # No env vars needed — should return an empty dict.
        secrets = main_module._validate_provider_secrets(SourceProvider.YAHOO_RSS)
        assert secrets == {}


# ---------------------------------------------------------------------------
# _build_ingestor
# ---------------------------------------------------------------------------


class TestBuildIngestor:
    def _base_config(self, provider: str, secrets: dict) -> dict:
        return {"provider": provider, "secrets": secrets}

    def test_alpha_vantage_returns_correct_type(self) -> None:
        config = self._base_config(
            SourceProvider.ALPHA_VANTAGE, {"ALPHA_VANTAGE_KEY": "key"}
        )
        ingestor = main_module._build_ingestor(config)
        assert isinstance(ingestor, AlphaVantageIngestor)

    def test_finnhub_returns_correct_type(self) -> None:
        config = self._base_config(SourceProvider.FINNHUB, {"FINNHUB_API_KEY": "key"})
        ingestor = main_module._build_ingestor(config)
        assert isinstance(ingestor, FinnhubIngestor)

    def test_yahoo_rss_returns_correct_type(self) -> None:
        config = self._base_config(SourceProvider.YAHOO_RSS, {})
        ingestor = main_module._build_ingestor(config)
        assert isinstance(ingestor, YahooFinanceIngestor)

    def test_ingestor_source_provider_matches(self) -> None:
        config = self._base_config(SourceProvider.YAHOO_RSS, {})
        ingestor = main_module._build_ingestor(config)
        assert ingestor.source_provider == SourceProvider.YAHOO_RSS


# ---------------------------------------------------------------------------
# run() — dry-run short-circuit
# ---------------------------------------------------------------------------


class TestRunDryRun:
    """Verify that dry_run=True never calls _publish_to_queue."""

    def _make_config(self, provider: str = SourceProvider.YAHOO_RSS, secrets: dict | None = None) -> dict:
        return {
            "provider": provider,
            "secrets": secrets or {},
            "ticker": "AAPL",
            "lookback_minutes": 60,
            "relevance_threshold": 0.5,
            "dry_run": True,
            "rabbitmq_host": "",
            "rabbitmq_port": 5672,
            "rabbitmq_queue": "raw-news",
        }

    def test_dry_run_does_not_publish(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from unittest.mock import MagicMock, patch
        from sentic_signal.models import NewsItem, SourceProvider
        from datetime import datetime, UTC

        fake_item = NewsItem(
            headline="Test",
            url="https://example.com/test",
            summary="summary",
            published=datetime.now(UTC),
            source_provider=SourceProvider.YAHOO_RSS,
            ticker="AAPL",
        )

        with (
            patch.object(main_module, "_build_ingestor") as mock_build,
            patch.object(main_module, "_publish_to_queue") as mock_publish,
        ):
            mock_ingestor = MagicMock()
            mock_ingestor.source_provider = SourceProvider.YAHOO_RSS
            mock_ingestor.fetch_news.return_value = [fake_item]
            mock_build.return_value = mock_ingestor

            main_module.run(self._make_config())

        mock_publish.assert_not_called()

    def test_dry_run_no_items_does_not_publish(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from unittest.mock import MagicMock, patch

        with (
            patch.object(main_module, "_build_ingestor") as mock_build,
            patch.object(main_module, "_publish_to_queue") as mock_publish,
        ):
            mock_ingestor = MagicMock()
            mock_ingestor.source_provider = SourceProvider.YAHOO_RSS
            mock_ingestor.fetch_news.return_value = []
            mock_build.return_value = mock_ingestor

            main_module.run(self._make_config())

        mock_publish.assert_not_called()
