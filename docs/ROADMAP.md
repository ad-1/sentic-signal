# Sentic-Signal — 2026 Roadmap

## Core Mission

Build an automated, provider-agnostic pipeline that:

1. **Aggregates** real-time ticker-specific news from multiple providers.
2. **Normalises** every response into a single Sentic-defined data contract — the system is designed around *our* schema, not any provider's.
3. **Analyses** each article for sentiment and materiality — using both provider-supplied signals (when available) and our own Sentic sentiment engine.
4. **Delivers** high-confidence signals through durable RabbitMQ queues to downstream consumers (Telegram alerts today, Sentic-Quant-Engine tomorrow).

### Why Provider-Agnostic?

We started with Alpha Vantage and have expanded to Yahoo Finance RSS. More providers will follow. The key design constraint is **zero vendor lock-in**: every provider is a plug-in that conforms to a standard `BaseIngestor` interface and outputs normalised `NewsItem` objects. If a provider disappears, hits rate limits, or degrades — the rest of the pipeline keeps running.

### Sentiment Strategy: Dual-Track

Some providers deliver sentiment (Alpha Vantage). Others don't (Yahoo RSS). Rather than choosing one source, we carry **both**:

| Field | Source | Purpose |
|---|---|---|
| `provider_sentiment` | Alpha Vantage, future providers | Free signal from the provider's own models. Preserved as-is. |
| `sentic_sentiment` | Our own analysis (FinBERT / LLM) | Consistent scoring across all articles, regardless of provider. |

This gives us: (a) a working pipeline before our own model is production-ready, (b) a baseline to validate and tune our model against, and (c) graceful degradation for providers that don't supply sentiment.

---

## Design Principles

| Principle | Implementation |
|---|---|
| **Provider-agnostic ingestion** | `BaseIngestor` protocol — every provider implements `fetch_news()` and returns `list[NewsItem]`. |
| **Our contract, not theirs** | `NewsItem` is the canonical schema this service owns. `Signal` lives in downstream repos. Providers adapt to our schema, not the other way around. |
| **Durable messaging** | RabbitMQ with persistent queues. If a consumer crashes, messages survive and are reprocessed. |
| **Independent scheduling** | Each ingestor runs on its own cron interval (AV every 2h, Yahoo every 15min). No global synchronisation required. |
| **Microservice boundaries at queues** | Each queue (`raw-news`, `analyzed-signals`, `notifications`) is a natural service boundary. |
| **Fail-open, log loudly** | If one provider fails, the others keep running. Errors are logged, never silently swallowed. |

---

## Current State (v0.3.0)

This repo is now a **dedicated news ingestor**. The Telegram notifier and analyst layers are separate microservices in their own repos (`sentic-notifier`, `sentic-analyst`), communicating via RabbitMQ queues.

| Component | Status | Notes |
|---|---|---|
| Alpha Vantage ingestor | ✅ Complete | `AlphaVantageIngestor` implements `BaseIngestor`. Fetches NEWS_SENTIMENT, filters by relevance. |
| Yahoo Finance RSS ingestor | ✅ Complete | `YahooFinanceIngestor` implements `BaseIngestor`. Wired into `main.py`. |
| Finnhub ingestor | ✅ Complete | `FinnhubIngestor` implements `BaseIngestor`. 60 req/min free tier. |
| RabbitMQ publisher | ✅ Complete | `RabbitMQPublisher` in `main.py`. RabbitMQ is the only dispatch target. |
| Pydantic data contracts | ✅ Complete | `NewsItem` carries `provider_sentiment`, `sentic_sentiment`, `source_provider`. `Signal` lives in downstream repos. |
| `BaseIngestor` protocol | ✅ Complete | Runtime-checkable Protocol. All providers conform. |
| Telegram notifier | ✅ Extracted | Moved to `sentic-notifier` repo. No longer part of this service. |
| Helm chart | 🔄 In progress | CronJob template updated. ConfigMap for env injection. Needs RabbitMQ subchart dependency. |
| Docker Compose (local) | ✅ Complete | RabbitMQ + ingestor for local development. |
| `values.yaml` → `.env` sync script | ✅ Complete | Shell script generates `.env` from `values.yaml` for VS Code development. |
| Analyst / LLM layer | ⬜ Stub | Lives in `sentic-analyst` repo. |
| CI/CD | ⚠️ Defined, not validated | `ci.yml` workflow exists. Unit tests confirmed passing locally. Image build, GHCR push, and tag-update PR not yet validated end-to-end (no successful run recorded). |

---

## Phased Roadmap

### Phase 1 — Provider Abstraction & Queue Integration ✅ Complete

**Goal:** Wire the existing components together through RabbitMQ so the pipeline runs as decoupled producers/consumers.

- [x] Define `BaseIngestor` protocol in `ingestor/__init__.py` with a standard `fetch_news() -> list[NewsItem]` interface.
- [x] Refactor `AlphaVantageIngestor` and `YahooFinanceIngestor` to implement `BaseIngestor`.
- [x] Add `FinnhubIngestor` — 60 req/min free tier, ticker-specific news endpoint.
- [x] Extend `NewsItem` model to carry `provider_sentiment` (from the source) alongside a future `sentic_sentiment` field.
- [x] Add a `source_provider` field to `NewsItem` so downstream consumers know where each article originated.
- [x] Wire ingestors → `RabbitMQPublisher` → `raw-news` queue in `main.py`. RabbitMQ is the only dispatch target.
- [x] Helm `values.yaml` as single source of truth for all config. Shell script generates `.env` from `values.yaml` for local development.
- [x] Docker Compose with RabbitMQ for local development and integration testing.

### Phase 2 — Analyst Worker (Consumer)

**Goal:** Build the "brain" that consumes from `raw-news`, deduplicates, scores sentiment, and publishes to `analyzed-signals`.

- [ ] Implement URL/title-hash deduplication (SQLite or in-memory set for MVP).
- [ ] Integrate a local sentiment model (vaderSentiment for speed, FinBERT for accuracy) to produce `sentic_sentiment`.
- [ ] Build the analyst worker as a RabbitMQ consumer that reads from `raw-news` and publishes to `analyzed-signals`.
- [ ] Preserve `provider_sentiment` when available; populate `sentic_sentiment` for all articles.
- [ ] Add materiality scoring (Gemini Flash LLM) for high-relevance signals — gated behind a feature flag.

### Phase 3 — Notifier & Infra Separation ✅ Complete

**Goal:** Extract notifier to its own microservice; define the shared RabbitMQ infrastructure boundary.

- [x] `TelegramNotifier` extracted to `sentic-notifier` repo — standalone RabbitMQ consumer.
- [x] `sentic-signal` is now a pure ingestor: fetch → normalise → publish to queue. No direct dispatch.
- [x] Shared RabbitMQ infrastructure managed via a dedicated `sentic-infra` repo (Helm + Bitnami subchart on minikube).
- [ ] Add configurable alert thresholds in `sentic-notifier` (e.g., only notify on `|sentic_sentiment| > 0.5`).

### Phase 4 — Deployment & CI/CD *(current priority)*

**Goal:** Deploy to minikube on Lenovo ThinkCentre i5 hardware; automate with GitHub Actions.

- [ ] `sentic-infra` repo: Helm chart for shared infrastructure (RabbitMQ Bitnami subchart, persistent volumes, queue declarations).
- [ ] Per-service Helm charts (`sentic-signal`, `sentic-analyst`, `sentic-notifier`) reference shared infra queue names via ConfigMap.
- [ ] Add Kubernetes `Secret` manifests for API keys (`ALPHA_VANTAGE_KEY`, `FINNHUB_API_KEY`) and queue credentials.
- [ ] GitHub Actions workflow: lint → unit tests → build Docker image → push to registry → Helm upgrade to minikube.
- [ ] Configure minikube on ThinkCentre with persistent volumes for RabbitMQ state.
- [ ] Add readiness probes and resource limits to CronJob spec.

### Phase 5 — Expand & Harden

**Goal:** Add more providers, improve resilience, connect to the broader Sentic ecosystem.

- [ ] Add Finnhub.io ingestor (60 req/min free tier — good for higher-frequency polling).
- [ ] Add SEC EDGAR ingestor for official filings (8-K, 10-Q).
- [ ] Expose a Sentiment API for consumption by `Sentic-Quant-Engine`.
- [ ] Integrate with `Sentic-Sync` for dynamic watchlist ingestion from IBKR.
- [ ] Persist processed signals to a datastore (Supabase or PostgreSQL) for sentiment drift tracking.
- [ ] RabbitMQ dead-letter queues for failed messages; retry logic with exponential backoff.

---

## Data Providers

Providers are prioritised by cost, rate limits, and signal quality:

| Provider | Tier | Sentiment? | Rate Limit (Free) | Status |
|---|---|---|---|---|
| Alpha Vantage | Financial API | ✅ Yes | 25 req/day | ✅ Implemented |
| Yahoo Finance RSS | Direct Feed | ❌ No | Unlimited | ✅ Implemented |
| Finnhub.io | Financial API | ❌ No | 60 req/min | ⬜ Planned |
| SEC EDGAR | Direct Feed | ❌ No | 10 req/sec | ⬜ Planned |
| Tiingo | Financial API | ❌ No | 1000 req/day | ⬜ Candidate |
| NewsAPI.ai | Broad News | ❌ No | 100 req/day | ⬜ Candidate |