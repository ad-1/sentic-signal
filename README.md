# 📡 Sentic-Signal

> AI-powered newsfeed for stock sentiment — part of the [Sentic Finance Lab](docs/ARCHITECTURE.md) ecosystem.

Sentic-Signal is an automated financial intelligence agent that fetches real-time news for your equity watchlist, filters it by relevance, and dispatches actionable sentiment alerts directly to your Telegram. It acts as the **Intelligence Layer** of the Sentic platform, feeding processed signals downstream to the Sentic-Quant-Engine.

---

## ✨ Features

- **Real-time news ingestion** via the Alpha Vantage `NEWS_SENTIMENT` API
- **Heuristic relevance filtering** — drops articles with a ticker relevance score below 0.5
- **Configurable lookback window** — only surfaces news from the last N minutes
- **Telegram notifications** with sentiment-coded emoji alerts (🟢🟡⚪️🟠🔴)
- **Dry-run mode** — test the full pipeline without calling paid APIs or sending messages
- **Pydantic data contracts** enforcing a consistent schema across all pipeline stages
- **Dockerised** for straightforward deployment

---

## 🏗️ Architecture

Sentic-Signal operates as a three-stage pipeline:

### 1. Ingestion
- Fetches the `NEWS_SENTIMENT` feed from **Alpha Vantage** for the configured ticker.
- Parses and validates each article into a `NewsItem` Pydantic model.
- Drops articles with a `ticker_relevance_score < 0.5` (heuristic hard filter).

### 2. Processing
- Applies a **lookback window filter** — only articles published within the last `NEWS_LOOKBACK_MINUTES` are forwarded.
- Each qualifying `NewsItem` is promoted to a `Signal` — the canonical output contract of the pipeline.
- *(Phase 3 — planned)* High-relevance signals will be passed to **Gemini Flash** for LLM materiality scoring and 3-bullet impact summaries.

### 3. Delivery
- **Telegram** — `TelegramNotifier` formats each `Signal` as a MarkdownV2 message and dispatches it to the configured chat or channel.
- *(Planned)* Structured JSON output for consumption by **Sentic-Quant-Engine**.
- *(Planned)* Persistence to **Supabase** for sentiment drift tracking.

For full architectural detail see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## 🚀 Installation & Setup

### Prerequisites

- Python 3.13+
- An [Alpha Vantage](https://www.alphavantage.co/support/#api-key) API key (free tier: 25 req/day)
- A Telegram bot token from [@BotFather](https://t.me/BotFather) and a target chat ID

### 1. Clone & install

```bash
git clone https://github.com/your-org/sentic-signal.git
cd sentic-signal
pip install -e ".[dev]"
```

### 2. Configure environment variables

Copy the example file and fill in your credentials:

```bash
cp .env.example .env
```

| Variable                | Required | Default          | Description                                    |
|-------------------------|----------|------------------|------------------------------------------------|
| `ALPHA_VANTAGE_KEY`     | ✅        | —                | Alpha Vantage API key                          |
| `TELEGRAM_BOT_TOKEN`    | ✅        | —                | Bot token from @BotFather                      |
| `TELEGRAM_CHAT_ID`      | ✅        | —                | Target chat/channel ID (negative for groups)   |
| `TICKER`                | ❌        | `AAPL`           | Single equity ticker symbol                    |
| `NEWS_LOOKBACK_MINUTES` | ❌        | `60`             | Only surface articles published within N mins  |
| `DRY_RUN`               | ❌        | `false`          | Set to `true` to log alerts without sending    |

---

## ▶️ Usage

### Run directly

```bash
python -m sentic_signal.main
```

### Run via installed entry point

```bash
sentic-signal
```

### Dry run (no API calls or Telegram messages sent)

```bash
DRY_RUN=true sentic-signal
```

### Run in Docker

```bash
docker build -t sentic-signal .
docker run --env-file .env sentic-signal
```

---

## 🔄 Pipeline Walkthrough

1. **Fetch** — For configured `TICKER`, call Alpha Vantage `NEWS_SENTIMENT`.
2. **Filter (relevance)** — Discard any article with `ticker_relevance_score < 0.5`.
3. **Filter (lookback)** — Discard articles older than `NEWS_LOOKBACK_MINUTES`.
4. **Promote** — Each qualifying `NewsItem` becomes a `Signal`.
5. **Notify** — `TelegramNotifier.send_batch()` dispatches all signals to your chat.

Example Telegram alert:
```
📡 *NVDA* | Bullish 🟢
🗞 NVIDIA announces next-generation chip architecture
📅 2026-04-15 13:00 UTC
🔗 Read Article
```

---

## 🗂️ Project Structure

```
sentic-signal/
├── .github/                # GitHub Actions, Agents, & Prompts
│   ├── workflows/          # CI/CD (GitHub Actions)
│   ├── agents/             # Copilot Custom Agents
│   └── prompts/            # Reusable Prompt Templates
├── deploy/                 # Infrastructure as Code
│   ├── k8s/                # Raw Kubernetes manifests
│   └── helm/               # Helm charts for AWS/Local k8s
├── docs/                   # Extended documentation
│   ├── ARCHITECTURE.md     # System architecture deep-dive
│   ├── ALPHA_VANTAGE.md    # Alpha Vantage API notes
│   └── ROADMAP.md          # Development roadmap
├── src/
│   └── sentic_signal/      # Core package
│       ├── main.py         # Pipeline entry point
│       ├── models.py       # Pydantic schemas (NewsItem, Signal)
│       ├── ingestor/       # Alpha Vantage ingestion logic
│       ├── analyst/        # Gemini/LLM logic (Phase 3)
│       └── notifier/       # Telegram dispatcher
├── tests/
│   ├── conftest.py         # Pytest fixtures
│   ├── unit/               # Logic tests (no external calls)
│   └── integration/        # Real API flow tests (mocked)
├── .env.example            # Template for required secrets
├── Dockerfile              # Container definition
├── pyproject.toml          # Dependencies & project metadata
└── CHANGELOG.md            # Version history
```

---

## 🧪 Testing

```bash
# Run all tests
pytest

# Unit tests only
pytest tests/unit/

# Integration tests only
pytest tests/integration/
```

Unit tests cover all logic in isolation (no external API calls). Integration tests validate real API flows using mocked HTTP responses.

---

## 🗺️ Roadmap

- [x] **Phase 1** — Alpha Vantage news ingestion with relevance filtering
- [x] **Phase 2** — Telegram notification dispatcher
- [ ] **Phase 3** — Gemini Flash LLM materiality scoring & impact summaries
- [ ] **Phase 4** — Dynamic ticker ingestion from `Sentic-Sync` (IBKR) microservice
- [ ] **Phase 5** — Sentiment API endpoint for `Sentic-Quant-Engine` consumption

---

## 🛠️ Best Practices

- **GitHub Actions permissions** — The CI workflow requires the repo's "Workflow permissions" to be set to **Read and write** (Settings → Actions → General). This allows `GITHUB_TOKEN` to push to GHCR and open the automated image-tag PR. Without it, the `build-and-push` and `update-image-tag` jobs will fail with a 403.
- **Data contracts** — All inter-component data flows through validated Pydantic models (`NewsItem`, `Signal`), preventing integration bugs.
- **Idempotency** — Article deduplication via URL/title hashing is planned to prevent repeated alerts.
- **Dry-run mode** — Full pipeline execution without any external side effects, safe for CI/CD.
- **Zero-trust secrets** — All credentials are injected via environment variables; no secrets are hardcoded.

---

## 📄 License

This project is part of the private Sentic Finance Lab. See [CHANGELOG.md](CHANGELOG.md) for version history.
