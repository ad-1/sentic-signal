# Changelog

All notable changes to **Sentic-Signal** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] - 0.4.x

### Changed
- **Runtime contract:** `PROVIDER` env var is now required. Unknown or absent values fail immediately with an explicit error listing valid options.
- **Single-ingestor model:** `main.py` builds exactly one ingestor per run. The previous auto-enable multi-provider model has been removed.
- **Provider-specific secret validation:** Missing required API keys (`ALPHA_VANTAGE_KEY`, `FINNHUB_API_KEY`) are detected before any network I/O; `yahoo_rss` requires no key.
- **Dry-run:** `DRY_RUN=true` now correctly suppresses queue publish and makes `RABBITMQ_HOST` optional.

### Added
- `tests/unit/test_main_provider.py` — 20 unit tests covering provider resolution, secret validation, ingestor factory, and dry-run dispatch.
- `deploy/sentic-signal-chart/values-alpha-vantage.yaml` — provider overlay for Alpha Vantage releases.
- `deploy/sentic-signal-chart/values-finnhub.yaml` — provider overlay for Finnhub releases.
- `PROVIDER` field in Helm ConfigMap; secret env vars in CronJob template are now conditional on `PROVIDER` value.

### Removed
- `YAHOO_RSS_ENABLED` env var — Yahoo RSS is selected by setting `PROVIDER=yahoo_rss`.
- Multi-provider auto-enable logic (`_build_ingestors`) replaced by single-provider factory (`_build_ingestor`).

## [0.1.1] - 2026-04-17

### Added
- **Initial Architecture:** Defined the Ingest-Filter-Analyze-Dispatch pipeline.
- **Data Ingestion:** Implemented Alpha Vantage `NEWS_SENTIMENT` API integration.
- **Environment Config:** Added `.env` support for API keys and ticker parameterization.
- **Microservice Design:** Drafted integration patterns for `Sentic-Sync` (IBKR) and `Sentic-Quant-Engine`.
- **Telegram Integration:** Linked Alpha Vantage news ingestion with Telegram notification system.

### Changed
- **Python Version:** Upgraded project requirements to Python 3.13 to leverage modern typing and performance improvements.

### Planned
- LLM Materiality Check layer using Gemini 3 Flash.
- Telegram integration for real-time signaling.
