# Changelog

All notable changes to **Sentic-Signal** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
