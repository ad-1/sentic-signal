# Sentic-Signal — Architecture

> AI-powered, provider-agnostic financial news sentiment pipeline.

Sentic-Signal is the **Intelligence Layer** of the Sentic Finance Lab. It ingests ticker-specific news from multiple providers, normalises it into a standard schema, analyses sentiment and materiality, and delivers high-confidence signals to downstream consumers.

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
├── .github/
│   └── workflows/            # GitHub Actions CI/CD
├── deploy/
│   └── sentic-signal-chart/  # Helm chart for K8s deployment
│       ├── Chart.yaml
│       ├── values.yaml
│       └── templates/
│           ├── cronjob.yaml        # Ingestor CronJob
│           ├── deployment-analyst.yaml   # (planned)
│           ├── deployment-notifier.yaml  # (planned)
│           └── _helpers.tpl
├── src/
│   └── sentic_signal/
│       ├── __init__.py
│       ├── main.py           # Pipeline entry point
│       ├── models.py         # Pydantic data contracts (NewsItem, Signal)
│       ├── ingestor/
│       │   ├── __init__.py         # BaseIngestor protocol (planned)
│       │   ├── alpha_vantage.py    # Alpha Vantage NEWS_SENTIMENT
│       │   ├── yahoo_finance_rss.py # Yahoo Finance RSS feeds
│       │   └── rabbitmq_publisher.py # Queue publisher utility
│       ├── analyst/
│       │   └── __init__.py         # Sentiment + materiality (planned)
│       └── notifier/
│           ├── __init__.py
│           └── telegram.py         # Telegram MarkdownV2 dispatcher
├── tests/
│   ├── conftest.py
│   ├── unit/
│   │   ├── test_alpha_vantage.py
│   │   └── test_telegram_notifier.py
│   └── integration/
│       └── test_verify_chat.py
├── Dockerfile
├── pyproject.toml
└── README.md
```

---

## Data Contract — The "Sentic Standard"

The core design decision: **we define the schema, providers adapt to it**. Every ingestor — regardless of source — outputs the same `NewsItem` model. This is what makes provider swaps trivial.

### NewsItem (Ingestor → Queue)

The normalised article representation. Every provider maps its raw response into this format.

| Field | Type | Description |
|---|---|---|
| `ticker` | `str` | Equity ticker symbol (e.g. `AAPL`). |
| `headline` | `str` | Article title. |
| `url` | `HttpUrl` | Canonical article URL. |
| `summary` | `str` | Short article summary. |
| `published` | `datetime` | UTC publication timestamp. |
| `relevance_score` | `float` (0–1) | How relevant the article is to the ticker. Provider-supplied or heuristically computed. |
| `sentiment` | `SentimentLabel \| None` | Provider-supplied sentiment (Alpha Vantage). `None` when unavailable (Yahoo, Finnhub). |
| `source_provider` | `str` | Origin provider identifier (planned — e.g. `alpha_vantage`, `yahoo_rss`). |

### Signal (Queue → Notifier / Quant Engine)

The dispatch-ready output. Enriched with Sentic's own analysis.

| Field | Type | Description |
|---|---|---|
| `ticker` | `str` | Equity ticker symbol. |
| `headline` | `str` | Article title. |
| `url` | `HttpUrl` | Canonical article URL. |
| `published` | `datetime` | UTC publication timestamp. |
| `summary` | `str` | Article summary. |
| `sentiment` | `SentimentLabel \| None` | Provider sentiment (preserved). |
| `sentic_sentiment` | `float \| None` | Sentic-computed sentiment score (planned). |
| `materiality` | `str \| None` | LLM-generated materiality assessment (planned). |

### SentimentLabel Enum

```
Bullish | Somewhat-Bullish | Neutral | Somewhat-Bearish | Bearish
```

---

## Provider Abstraction

Each news provider implements a common interface. The pipeline doesn't know or care which provider produced a `NewsItem`.

```python
class BaseIngestor(Protocol):
    """Standard interface all news providers must implement."""

    def fetch_news(
        self,
        tickers: list[str],
        relevance_threshold: float = 0.5,
    ) -> list[NewsItem]:
        """Fetch and normalise news for the given tickers."""
        ...
```

### Current Providers

**Alpha Vantage** (`ingestor/alpha_vantage.py`)
- Calls the `NEWS_SENTIMENT` endpoint per ticker.
- Provides relevance scores and sentiment labels natively.
- Rate-limited to 25 req/day on free tier — schedule accordingly (every 2h).
- Rate-limit exhaustion detected via `"Note"` / `"Information"` JSON fields.

**Yahoo Finance RSS** (`ingestor/yahoo_finance_rss.py`)
- Parses RSS feeds at `https://finance.yahoo.com/rss/2.0?ticker={ticker}`.
- Zero cost, no rate limits — suitable for high-frequency polling (every 15min).
- No native sentiment — `sentiment` field is `None`; relies on the analyst worker.
- Relevance is heuristically scored via ticker-in-text matching.

### Adding a New Provider

1. Create `ingestor/your_provider.py`.
2. Implement `fetch_news(tickers, relevance_threshold) -> list[NewsItem]`.
3. Map the provider's raw response to `NewsItem` fields.
4. Register the provider in the `IngestorRunner` config.

---

## Queue Architecture (RabbitMQ)

RabbitMQ provides durable, persistent message queues that decouple the pipeline stages. If a consumer crashes, messages survive on disk and are reprocessed on restart.

### Queues

| Queue | Producer | Consumer | Message Type |
|---|---|---|---|
| `raw-news` | Ingestors (AV, Yahoo, etc.) | Analyst Worker | `NewsItem` (JSON) |
| `analyzed-signals` | Analyst Worker | Telegram Notifier, Quant Engine | `Signal` (JSON) |

### Message Flow

1. **Ingestors** run on independent cron schedules. Each fetches from its provider, normalises to `NewsItem`, and publishes to `raw-news` with `delivery_mode=2` (persistent).
2. **Analyst Worker** consumes from `raw-news`. It deduplicates (URL hash), runs sentiment analysis, and publishes enriched `Signal` objects to `analyzed-signals`.
3. **Notifier** consumes from `analyzed-signals`. Filters by alert threshold and dispatches to Telegram.

### Resilience

- **Durable queues** — messages survive broker restarts.
- **Persistent messages** — `delivery_mode=2` on all publishes.
- **Independent producers** — if Alpha Vantage is rate-limited, Yahoo RSS keeps feeding the pipeline.
- **Dead-letter queues** (planned) — failed messages are routed to a DLQ for inspection rather than dropped.

---

## Aggregation Strategy

Providers run **independently on their own schedules**. There is no global "fetch all sources, then process" step. This is intentional:

- Alpha Vantage has a 25 req/day limit → run every 2 hours.
- Yahoo RSS is unlimited → run every 15 minutes.
- Finnhub (planned) allows 60 req/min → run every 30 minutes.

Each ingestor pushes to the same `raw-news` queue. The analyst worker processes messages as they arrive, regardless of which provider produced them. This means:

- No provider blocks another.
- The pipeline is always live as long as at least one provider is running.
- Adding a new provider doesn't require changes to the analyst or notifier.

---

## Deployment Architecture

### Target Environment

- **Hardware:** Lenovo ThinkCentre i5 running minikube.
- **Orchestration:** Kubernetes via Helm charts.
- **CI/CD:** GitHub Actions → build Docker image → push to registry → Helm upgrade.

### Kubernetes Resources

```
┌─────────────────────────────────────────────┐
│              minikube cluster                │
│                                             │
│  ┌──────────────────┐  ┌────────────────┐   │
│  │ CronJob:         │  │ Deployment:    │   │
│  │ ingestor-av      │  │ analyst-worker │   │
│  │ (every 2h)       │  │ (1 replica)    │   │
│  └──────────────────┘  └────────────────┘   │
│                                             │
│  ┌──────────────────┐  ┌────────────────┐   │
│  │ CronJob:         │  │ Deployment:    │   │
│  │ ingestor-yahoo   │  │ notifier       │   │
│  │ (every 15m)      │  │ (1 replica)    │   │
│  └──────────────────┘  └────────────────┘   │
│                                             │
│  ┌──────────────────────────────────────┐   │
│  │ StatefulSet: RabbitMQ (Bitnami)      │   │
│  │ - PersistentVolume for message state │   │
│  └──────────────────────────────────────┘   │
│                                             │
│  ┌──────────────────────────────────────┐   │
│  │ Secret: sentic-secrets               │   │
│  │ - ALPHA_VANTAGE_KEY                  │   │
│  │ - TELEGRAM_BOT_TOKEN                 │   │
│  │ - TELEGRAM_CHAT_ID                   │   │
│  │ - RABBITMQ_PASSWORD                  │   │
│  └──────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

### Helm Chart Structure (planned)

```yaml
# values.yaml — key sections
rabbitmq:
  enabled: true           # Deploy RabbitMQ as a subchart (Bitnami)

ingestors:
  alphaVantage:
    schedule: "0 */2 * * *"
    enabled: true
  yahooRss:
    schedule: "*/15 * * * *"
    enabled: true

analyst:
  replicas: 1

notifier:
  replicas: 1
  alertThreshold: 0.5
```

---

## CI/CD Pipeline (GitHub Actions)

```
push/PR → lint (ruff) → unit tests (pytest) → build Docker image
                                                      │
                                              push to registry
                                                      │
                                              helm upgrade (minikube)
```

### Stages

1. **Lint** — `ruff check src/ tests/`
2. **Unit Tests** — `pytest tests/unit/ --cov`
3. **Integration Tests** — `pytest tests/integration/` (with mocked APIs)
4. **Docker Build** — Multi-stage build from `Dockerfile`
5. **Push** — Push image to container registry (GHCR or Docker Hub)
6. **Deploy** — `helm upgrade --install sentic-signal ./deploy/sentic-signal-chart`

---

## Configuration

All configuration is via environment variables. No hardcoded secrets.

| Variable | Required | Default | Description |
|---|---|---|---|
| `ALPHA_VANTAGE_KEY` | ✅ | — | Alpha Vantage API key |
| `TELEGRAM_BOT_TOKEN` | ✅ | — | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | ✅ | — | Target chat/channel ID |
| `TICKERS` | ❌ | `AAPL,TSLA,NVDA` | Comma-separated equity tickers |
| `NEWS_LOOKBACK_MINUTES` | ❌ | `60` | Only surface articles within N minutes |
| `NEWS_RELEVANCE_THRESHOLD` | ❌ | `0.5` | Minimum relevance score to include |
| `DRY_RUN` | ❌ | `false` | Log alerts without sending |
| `RABBITMQ_HOST` | ❌ | `localhost` | RabbitMQ server host |
| `RABBITMQ_PORT` | ❌ | `5672` | RabbitMQ server port |
| `RABBITMQ_QUEUE` | ❌ | `news_queue` | Default queue name |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.13 |
| Data Contracts | Pydantic v2 |
| HTTP Client | requests |
| RSS Parsing | feedparser |
| Message Broker | RabbitMQ (pika client) |
| Sentiment (planned) | vaderSentiment / FinBERT |
| LLM (planned) | Gemini Flash |
| Containerisation | Docker (multi-stage) |
| Orchestration | Kubernetes (minikube) |
| Packaging | Helm 3 |
| CI/CD | GitHub Actions |