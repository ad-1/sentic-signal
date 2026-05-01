# Sentic-Signal - 2026 Roadmap

## Scope Statement

This roadmap describes the evolution of the `sentic-signal` repository.

`sentic-signal` is the ingestion boundary of the broader Sentic platform:

- fetch provider news
- normalize to `NewsItem`
- publish to RabbitMQ `raw-news`

Sentiment scoring, multi-agent analysis, and notifications are downstream
responsibilities in other services.

---

## Core Mission

1. Aggregate ticker-specific news from multiple providers.
2. Normalize all provider output into a strict Sentic contract (`NewsItem`).
3. Publish durable `raw-news` events for downstream pipeline services.
4. Deploy providers as isolated release units using a shared image and shared
   contracts (ADR-001).

---

## Design Principles

| Principle | Implementation |
|---|---|
| Provider-agnostic ingestion | `BaseIngestor` protocol for all adapters. |
| Sentic-owned contract | Providers adapt to `NewsItem`; the schema does not adapt to providers. |
| Single responsibility | This service ends at `raw-news`; no in-service analysis. |
| Durable messaging | RabbitMQ queues with persistent delivery. |
| Operational isolation | Provider-specific deployments from one shared image (in progress). |
| Explicit configuration | Runtime should fail fast on invalid provider/secret config. |

---

## Current State (v0.4.x)

| Component | Status | Notes |
|---|---|---|
| Alpha Vantage ingestor | Complete | Adapter implemented and wired into runtime. |
| Yahoo Finance RSS ingestor | Complete | Adapter implemented and wired into runtime. |
| Finnhub ingestor | Complete | Adapter implemented and wired into runtime. |
| Canonical contract | Complete | `NewsItem` includes `source_provider`, `ingested_at`, computed `item_id`. |
| RabbitMQ publisher | Complete | Publishes to `raw-news`. |
| Helm chart baseline | Complete | CronJob + ConfigMap templates render; `PROVIDER` added; secrets conditional by provider. |
| Runtime selection model | Complete | `PROVIDER` required; single ingestor per run; fail-fast secret validation. |
| Provider overlay values | Complete | `values-alpha-vantage.yaml`, `values-finnhub.yaml` overlays created. |
| Helm CI lint/render matrix | Complete | All three provider overlays validated in CI (`helm-lint` job with matrix strategy). |
| Argo CD Application manifests | Complete | `sentic-signal-yahoo-rss`, `sentic-signal-alpha-vantage`, `sentic-signal-finnhub` in sentic-infra. |
| CI/CD pipeline validation | In progress | Workflow exists; full publish and deploy validation still pending. |
| Production deployment | Not started | Pre-release design and preparation stage. |

---

## Queue Boundary Context

`sentic-signal` ownership ends at `raw-news`.

Platform context (outside this repo):

- `raw-news` -> `sentic-extractor`
- `rich-content` -> `sentic-aggregator`
- `enriched-batches` -> `sentic-analyst`
- `analysis-results` / `notifications` -> downstream consumers

---

## Phased Roadmap

### Phase 1 - Provider Adapters and Raw-News Boundary (Complete)

- [x] Define `BaseIngestor` protocol.
- [x] Implement Alpha Vantage, Yahoo RSS, and Finnhub adapters.
- [x] Publish normalized `NewsItem` events to `raw-news`.
- [x] Keep this repo scoped to ingestion only.

### Phase 2 - Service Boundary Clarification (Complete)

- [x] Align to ADR-003 five-stage platform boundary.
- [x] Remove in-service notifier/analyst assumptions.
- [x] Keep `sentic-signal` as pure producer to `raw-news`.

### Phase 3 - Provider-Specific Deployment Model (Complete)

Goal: implement ADR-001 in pre-release environments.

- [x] Define target architecture in ADR-001 with pre-release gates.
- [x] Fix Helm helper include mismatch so chart renders successfully.
- [x] Implement explicit `PROVIDER` runtime selection.
- [x] Enforce one ingestor per run and fail-fast provider validation.
- [x] Add provider-specific required-secret validation.
- [x] Remove auto-enable behavior based only on key presence.
- [x] Add runtime unit tests for provider selection and validation.
- [x] Create provider overlay values for alpha_vantage, yahoo_rss, finnhub.
- [x] Add CI render/lint matrix for all provider overlays.
- [x] Add Argo CD Application manifests per provider release in sentic-infra.

### Phase 4 - CI/CD Hardening

Goal: prove repeatable artifact and deployment flow.

- [ ] Validate image build and push to GHCR end-to-end.
- [ ] Validate image tag update workflow for deployment values.
- [ ] Validate Trivy scan execution and gating behavior.
- [ ] Add/expand integration tests for publish path and queue contract.

### Phase 5 - Launch Readiness (First Release)

Goal: transition from pre-release validation to first live deployment.

- [ ] Deploy provider-specific releases in launch environment.
- [ ] Achieve pre-release gate of 3/3 successful scheduled runs per provider.
- [ ] Verify secret isolation per provider release.
- [ ] Publish launch checklist and runbook.
- [ ] Freeze one shared image tag across provider releases for launch.

### Phase 6 - Expand and Harden

Goal: extend source coverage and resilience after launch.

Tier 2 direct feeds:

- [ ] Add Stat News RSS ingestor (`source_provider=stat_news_rss`).
- [ ] Add SEC EDGAR ingestor (`source_provider=sec_edgar`).

Resilience and platform integration:

- [ ] Add dead-letter queue strategy and retry policy.
- [ ] Integrate dynamic watchlist inputs from `sentic-sync`.
- [ ] Expand provider conformance test suite.

---

## Success Metrics

### Pre-Release Gates

- `helm template` passes for base and every provider overlay.
- 3/3 successful scheduled runs per provider in launch environment.
- 0 secret-scope violations across provider deployments.

### Post-Launch Targets

- >= 99% CronJob success rate per provider over rolling 7 days.
- >= 99.5% publish success ratio to `raw-news` per provider.
- Provider deployment changes remain isolated (no cross-provider restart requirement).

---

## Provider Landscape

| Provider | Tier | Rate Limit (Free) | Status |
|---|---|---|---|
| Alpha Vantage | Tier 1 funnel | 25 req/day | Implemented |
| Yahoo Finance RSS | Tier 1 funnel | Unlimited | Implemented |
| Finnhub | Tier 1 funnel | 60 req/min | Implemented |
| Stat News RSS | Tier 2 direct feed | Unlimited | Planned |
| SEC EDGAR | Tier 2 direct feed | 10 req/sec | Planned |

---

## Decision References

- ADR-001 provider-specific deployment model:
  `docs/adr/ADR-001-PROVIDER-SPECIFIC-DEPLOYMENTS.md`
- ADR-003 five-stage platform architecture:
  `../sentic-infra/docs/adr/ADR-003-PIPELINE-ARCHITECTURE.md`