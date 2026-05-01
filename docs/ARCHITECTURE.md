# Sentic-Signal - Architecture

> Provider-agnostic news ingestion service for the Sentic platform.

Sentic-Signal is the discovery and normalization stage of the wider Sentic
pipeline. Its responsibility is to fetch ticker-specific news from providers,
normalize every item into the Sentic-defined `NewsItem` contract, and publish
to RabbitMQ `raw-news`.

This service does not perform sentiment scoring or multi-agent analysis.

---

## System Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          SENTIC-SIGNAL PIPELINE                         │
│                                                                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                     │
│  │ Alpha       │  │ Yahoo       │  │ Finnhub     │  ... more providers  │
│  │ Vantage     │  │ Finance RSS │  │ (planned)   │                     │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘                     │
│         │                │                │                             │
│         │  BaseIngestor  │   interface    │                             │
│         └────────┬───────┴───────┬────────┘                             │
│                  │               │                                      │
│                  ▼               ▼                                      │
│           ┌─────────────────────────┐                                   │
│           │    Normalised NewsItem   │  ← Sentic-defined data contract  │
│           └────────────┬────────────┘                                   │
│                        │                                                │
│                        ▼                                                │
│              ┌──────────────────┐                                       │
│              │   RabbitMQ       │                                       │
│              │   raw-news queue │                                       │
│              └────────┬─────────┘                                       │
│                       │                                                 │
│                       ▼                                                 │
│              ┌──────────────────┐                                       │
│              │  Analyst Worker  │                                       │
│              │  - Dedup         │                                       │
│              │  - Sentiment     │                                       │
│              │  - Materiality   │                                       │
│              └────────┬─────────┘                                       │
│                       │                                                 │
│                       ▼                                                 │
│              ┌───────────────────────┐                                  │
│              │   RabbitMQ            │                                  │
│              │   analyzed-signals    │                                  │
│              └────────┬──────────────┘                                  │
│                       │                                                 │
│              ┌────────┴──────────┐                                      │
│              ▼                   ▼                                      │
│     ┌────────────────┐  ┌───────────────────┐                          │
│     │  Telegram      │  │  Sentic-Quant     │                          │
│     │  Notifier      │  │  Engine (planned) │                          │
│     └────────────────┘  └───────────────────┘                          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
sentic-signal/
|- deploy/
|  |- sentic-signal-chart/
|  |  |- Chart.yaml
|  |  |- values.yaml
|  |  |- values-dev.yaml
|  |  |- values-alpha-vantage.yaml
|  |  |- values-finnhub.yaml
|  |  |- templates/
|  |  |  |- _helpers.tpl
|  |  |  |- configmap.yaml
|  |  |  |- cronjob.yaml
|- scripts/
|  |- gen-env.sh
|- src/
|  |- sentic_signal/
|  |  |- main.py
|  |  |- models.py
|  |  |- ingestor/
|  |  |  |- __init__.py
|  |  |  |- alpha_vantage.py
|  |  |  |- finnhub.py
|  |  |  |- yahoo_finance_rss.py
|  |  |- publisher/
|  |  |  |- rabbitmq_publisher.py
|- tests/
|  |- conftest.py
|  |- unit/
|  |  |- test_alpha_vantage.py
|  |  |- test_main_provider.py
|  |- integration/
|- Dockerfile
|- pyproject.toml
|- README.md
```

---

## Data Contract - NewsItem

The core design rule is unchanged: Sentic defines the schema, providers adapt
to Sentic's schema.

### NewsItem (published by sentic-signal)

| Field | Type | Description |
|---|---|---|
| `ticker` | `str` | Equity ticker symbol (for example `AAPL`). |
| `headline` | `str` | Article title. |
| `url` | `HttpUrl` | Canonical article URL. |
| `summary` | `str | None` | Optional provider summary. |
| `published` | `AwareDatetime` | Provider publication timestamp (UTC). |
| `ingested_at` | `AwareDatetime` | Ingestion timestamp assigned by sentic-signal (UTC). |
| `source_provider` | `SourceProvider` | Typed origin provider enum. |
| `item_id` | `uuid.UUID` (computed) | Stable UUID5 from `url + ticker` for deduplication. |

Notes:

- Provider-specific sentiment and relevance metadata are ingestion-time concerns
  and do not cross this boundary in the canonical `NewsItem` contract.
- Downstream contracts such as `AnalysisResult` are owned by downstream services.

### SourceProvider Enum

Current implemented values:

- `alpha_vantage`
- `yahoo_rss`
- `finnhub`

Planned values already reserved in code for Tier 2 direct feeds:

- `stat_news_rss`
- `sec_edgar`

---

## Provider Abstraction

Every provider adapter implements one protocol:

```python
class BaseIngestor(Protocol):
    source_provider: SourceProvider

    def fetch_news(
        self,
        ticker: str,
        relevance_threshold: float = 0.5,
    ) -> list[NewsItem]:
        ...
```

### Implemented Providers

Alpha Vantage:

- Endpoint: `NEWS_SENTIMENT`
- Native ticker relevance data
- Free-tier limit: 25 requests/day

Yahoo Finance RSS:

- Endpoint: `https://finance.yahoo.com/rss/2.0?ticker={ticker}`
- No API key required
- Relevance estimated heuristically from ticker mention

Finnhub:

- Endpoint: company-news API
- Free-tier limit: 60 requests/minute
- No provider sentiment in canonical output

---

## Runtime Behavior

### Current Implementation (v0.4.x — ADR-001 Phase 1)

Configuration is loaded from environment in `main.py`.

- `PROVIDER` required — must be one of `alpha_vantage`, `finnhub`, `yahoo_rss`.
- Exactly one ingestor is built per run; unknown provider values fail immediately.
- Provider-specific secrets validated before any network I/O:
  - `ALPHA_VANTAGE_KEY` required iff `PROVIDER=alpha_vantage`
  - `FINNHUB_API_KEY` required iff `PROVIDER=finnhub`
  - `yahoo_rss` requires no API key
- `RABBITMQ_HOST` required (skipped when `DRY_RUN=true`).
- `RABBITMQ_QUEUE` defaults to `raw-news`.

Execution model:

1. Resolve and validate `PROVIDER`.
2. Validate provider-specific secrets (fail-fast).
3. Build exactly one ingestor.
4. Fetch news for configured ticker.
5. Apply lookback filtering.
6. Publish qualifying `NewsItem` objects to RabbitMQ `raw-news` (unless `DRY_RUN`).

Error handling is fail-fast:

- Missing or unknown `PROVIDER` raises `RuntimeError` before any work begins.
- Missing required provider secret raises `RuntimeError` before network I/O.

---

## Queue Boundaries

### Boundary Owned by This Repo

| Queue | Publisher | Consumer |
|---|---|---|
| `raw-news` | `sentic-signal` | `sentic-extractor` |

### Downstream Platform Topology (for context)

| Queue | Publisher | Consumer |
|---|---|---|
| `rich-content` | `sentic-extractor` | `sentic-aggregator` |
| `enriched-batches` | `sentic-aggregator` | `sentic-analyst` |
| `analysis-results` | `sentic-analyst` | `sentic-quant` |
| `notifications` | `sentic-analyst`, `sentic-quant` | `sentic-notifier` |

---

## Deployment Architecture

### Current Pre-Release State

- Kubernetes CronJob chart exists in `deploy/sentic-signal-chart/`
- Config is rendered into a ConfigMap
- Provider keys are injected from Kubernetes Secret refs
- Deployment has not been launched to production yet

### Target Pre-Release Deployment Model (ADR-001)

One shared image, multiple provider-specific releases:

- `sentic-signal-alpha-vantage`
- `sentic-signal-yahoo-rss`
- `sentic-signal-finnhub`

Rules:

- exactly one provider per release
- provider-specific schedules and resources
- strict secret isolation per provider release

---

## CI/CD Status

Current state:

- workflows are defined
- unit tests are passing locally
- end-to-end pipeline validation is still in progress

Expected flow:

1. lint and unit test
2. build image
3. push image
4. update deployment values
5. deploy via GitOps

---

## Configuration

### Current Runtime Variables

| Variable | Required | Default | Notes |
|---|---|---|---|
| `PROVIDER` | Yes | none | Must be one of `alpha_vantage`, `finnhub`, `yahoo_rss`. Fail-fast if absent or unknown. |
| `TICKER` | No | `AAPL` | Single ticker per run. |
| `NEWS_LOOKBACK_MINUTES` | No | `60` | Lookback filter window. |
| `NEWS_RELEVANCE_THRESHOLD` | No | `0.5` | Provider relevance filter threshold. |
| `DRY_RUN` | No | `false` | When `true`, skips queue publish and bypasses `RABBITMQ_HOST` requirement. |
| `ALPHA_VANTAGE_KEY` | Conditional | none | Required iff `PROVIDER=alpha_vantage`. |
| `FINNHUB_API_KEY` | Conditional | none | Required iff `PROVIDER=finnhub`. |
| `RABBITMQ_HOST` | Yes (non-dry) | none | Broker host. |
| `RABBITMQ_PORT` | No | `5672` | Broker port. |
| `RABBITMQ_QUEUE` | No | `raw-news` | Publish queue. |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.13 |
| Data contracts | Pydantic v2 |
| HTTP clients | `requests`, `feedparser` |
| Message broker | RabbitMQ (`pika`) |
| Containerization | Docker |
| Orchestration | Kubernetes + Helm |
| CI/CD | GitHub Actions + GitOps |

---

## Related Decisions

- ADR-001 provider-specific deployments: `docs/adr/ADR-001-PROVIDER-SPECIFIC-DEPLOYMENTS.md`
- ADR-003 five-stage platform boundary: `../sentic-infra/docs/adr/ADR-003-PIPELINE-ARCHITECTURE.md`