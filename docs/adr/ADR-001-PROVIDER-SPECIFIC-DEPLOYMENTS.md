# ADR-001: Provider-Specific Deployments for Sentic-Signal

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-04-30 |
| Deciders | Andrew Davies |
| Context | Deployment model for provider adapters in sentic-signal |

## Context

Sentic-Signal currently runs as a single CronJob deployment that can execute multiple providers in one process, depending on environment configuration. Provider enablement is currently coupled to a shared runtime config (for example, API-key presence and provider flags), and all enabled providers run within the same release unit.

This has worked for early delivery, but provider onboarding now raises operational risk:

- Adding or changing one provider would change behavior of a shared runtime.
- Providers have different rate limits, schedules, error modes, and secret requirements.
- Launch and fallback behavior would be tied to one deployment unit.

At the same time, the service contract must remain stable:

- `NewsItem` stays the canonical output model.
- Provider adapters must keep implementing the same ingestor interface.
- Queue topology and downstream boundaries from ADR-003 remain unchanged.

## Decision Drivers

- Reduce blast radius when adding or modifying providers.
- Allow provider-specific schedules and operational tuning.
- Keep one shared codebase and one shared container image.
- Preserve the `NewsItem -> raw-news` contract.
- Keep provider onboarding simple and repeatable.

## Options Considered

### Option A: Keep one multi-provider deployment (status quo)

One release runs all enabled providers.

Pros:

- Lowest deployment and release complexity.
- Fewer Kubernetes resources.

Cons:

- Larger blast radius for provider changes.
- One schedule policy for mixed provider economics.
- Shared runtime config can cause unintended cross-provider effects.

### Option B: One codebase/image per provider

Split providers into separate service repos or separate images.

Pros:

- Strong runtime and release isolation.
- Team ownership can be fully provider-specific.

Cons:

- High maintenance overhead and code duplication risk.
- Contract drift risk across provider-specific implementations.
- Slower onboarding due to repeated scaffolding.

### Option C: One shared image, multiple provider-specific deployments (proposed)

Deploy the same sentic-signal image multiple times, each release configured for exactly one provider.

Pros:

- Strong operational isolation without codebase fragmentation.
- Independent schedules, resource settings, and secret scopes.
- Simple onboarding pattern: implement adapter once, add one deployment config.

Cons:

- More release objects to manage.
- Requires config discipline to prevent drift between provider releases.

## Decision (Proposed)

Adopt Option C with strict shared contracts and direct pre-release implementation.

Sentic-Signal stays one codebase and one image, deployed multiple times with
provider-specific runtime config. Example release names:

- `sentic-signal-alpha-vantage`
- `sentic-signal-yahoo-rss`
- `sentic-signal-finnhub`

Each deployment runs exactly one provider adapter and publishes normalized
`NewsItem` objects to `raw-news`.

## Target Architecture (Concrete)

### Deployment Topology

- One Helm chart, one shared image, one release per provider.
- One Argo CD Application per provider release in `sentic-infra/manifests/apps/`.
- Independent schedules, resources, retries, and alerting per provider release.

### Strict Shared Contracts

| Contract | Owner | Must Never Drift |
|---|---|---|
| `NewsItem` schema | `sentic-signal` | Required fields and field semantics stay stable across providers. |
| Ingestor interface (`fetch_news`) | `sentic-signal` | All providers return `list[NewsItem]`; same method signature for all adapters. |
| Queue boundary (`raw-news`) | `sentic-infra` + downstream consumers | Queue name and message contract stay stable across all provider releases. |
| Provider identifier set | `sentic-signal` | Allowed values are fixed and validated (`alpha_vantage`, `yahoo_rss`, `finnhub`). |
| Image tag policy | platform | All provider releases pin to same image tag unless exception is explicitly approved. |

### Runtime Selection Contract

| Variable | Required | Example | Rule |
|---|---|---|---|
| `PROVIDER` | Yes (provider-specific mode) | `alpha_vantage` | Must be one of `alpha_vantage`, `yahoo_rss`, `finnhub`. |
| `TICKER` | Yes | `TSLA` | Existing canonical single ticker input. |
| `NEWS_LOOKBACK_MINUTES` | No | `60` | Existing filter control. |
| `NEWS_RELEVANCE_THRESHOLD` | No | `0.5` | Existing filter control. |
| `ALPHA_VANTAGE_KEY` | Conditional | `...` | Required iff `PROVIDER=alpha_vantage`. |
| `FINNHUB_API_KEY` | Conditional | `...` | Required iff `PROVIDER=finnhub`. |

Validation rules:

- Provider-specific mode fails fast on missing required provider secrets.
- Exactly one ingestor instance is created per run.
- Unknown provider values fail fast with explicit configuration errors.
- Multi-provider runtime fallback is not implemented in this rollout.

### Secret Scope Matrix

| Release | Required Secrets | Must Not Be Mounted |
|---|---|---|
| `sentic-signal-alpha-vantage` | `ALPHA_VANTAGE_KEY` | `FINNHUB_API_KEY` |
| `sentic-signal-finnhub` | `FINNHUB_API_KEY` | `ALPHA_VANTAGE_KEY` |
| `sentic-signal-yahoo-rss` | none | provider API keys |

### Helm and Release Model

- Shared base values: image, RabbitMQ host/queue, common defaults.
- Provider overlays: `PROVIDER`, schedule, resources, secret references.
- Each release can tune schedule/resources independently.
- Chart rendering must pass for every provider overlay before merge.

### Service Boundary Impact

No queue contract changes are introduced by this ADR.

- `sentic-signal` still publishes `NewsItem` to `raw-news`.
- `sentic-extractor`, `sentic-aggregator`, and `sentic-analyst` stay unchanged.
- ADR-003 pipeline boundaries remain valid.

## Ambiguity Check and Readiness Decision

Decision: begin implementation immediately.

No strategic ambiguity remains. This project is pre-release and not yet deployed,
so this ADR does not require backward compatibility or live cutover choreography.
The remaining blockers are implementation hygiene:

1. Helm template baseline must be fixed first.
   - Current chart render fails because templates call `sentic-signal.fullname`
     while helpers define `sentic-signal-chart.fullname`.
2. Runtime contract must be strict from day one.
   - `PROVIDER` is required and must map to exactly one ingestor.
3. Release scaffolding must enforce secret isolation.
   - Each provider release only mounts its required secrets.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Release config drift across providers | Shared base values plus minimal provider overlays; CI `helm template` checks per provider. |
| Version skew across provider releases | Default to one shared image tag across all provider releases. |
| Queue bursts from synchronized schedules | Stagger provider schedules by design. |
| Hidden contract regressions | Add provider conformance tests for `NewsItem` contract and provider id. |
| Accidental multi-provider execution via misconfiguration | Enforce required `PROVIDER` and fail if more than one provider path is enabled. |

## Phased Implementation Plan (Pre-Release)

### Phase 0: Ambiguity Closure and Baseline Hardening — Complete

Goal: eliminate execution ambiguity before runtime behavior changes.

Work:

- [x] Fix Helm helper naming mismatch so chart renders reliably.
- [x] Lock provider id vocabulary and validation behavior.
- [x] Lock release naming convention and chart overlay structure.
- [x] Define launch-readiness gate criteria.

Exit criteria:

- `helm template` succeeds for base values and each provider overlay.
- Phase gates and launch checks are documented and approved.

Fallback point:

- Revert chart/template commits; no deployed behavior exists yet.

### Phase 1: Runtime Refactor (Single-Provider by Design) — Complete

Goal: enforce explicit single-provider execution as the only runtime mode.

Work:

- [x] Add explicit `PROVIDER` selection in `main.py`.
- [x] Build exactly one ingestor when `PROVIDER` is set.
- [x] Add provider-specific required-secret validation.
- [x] Add unit tests for provider selection, fail-fast secret validation, and invalid provider handling.

Exit criteria met:

- [x] Test suite passes with new provider-selection tests (39/39 unit tests pass).
- [x] Provider-specific mode verified for all providers locally.
- [x] No multi-provider fallback path remains in runtime code.

Fallback point:

- Revert runtime changes in git before release image is promoted.

### Phase 2: Helm Multi-Release Scaffolding — Complete

Goal: codify provider-specific releases using the shared chart.

Work:

- [x] Add provider overlays (`values-alpha-vantage.yaml`, `values-finnhub.yaml`; yahoo_rss is the default in `values.yaml`).
- [x] Add provider-specific secret wiring conditional on `PROVIDER` value.
- [x] Ensure non-required secrets are not mounted.
- [x] Add CI checks: `helm template` and `helm lint` for each provider overlay (matrix job in `ci.yml`).

Exit criteria met:

- All overlays render and lint successfully.
- Secrets and env vars match secret-scope matrix.

Fallback point:

- Revert overlay and template changes in git before launch.

### Phase 3: Integration and System Validation — In Progress

Goal: prove deployment behavior in pre-release environments.

Work completed:

- [x] Argo CD Application manifests created in `sentic-infra/manifests/apps/` for all three providers.
- [x] Sync-wave ordering: `yahoo-rss` at wave 21 (no secret dependency); `alpha-vantage` and `finnhub` at wave 22.

Validation sequence per provider (pending live cluster):

1. Deploy corresponding provider-specific release.
2. Execute at least 3 successful scheduled runs.
3. Check error rate, publish success, and schema conformance.
4. Verify only expected secrets are mounted.

Exit criteria per provider:

- Job success rate and publish success meet target metrics.
- No schema validation regressions.
- Secret scope matrix verified by environment inspection.

Fallback point per provider:

- Suspend failing provider release and fix forward before launch.

### Phase 4: Launch Readiness and First Release

Goal: promote validated provider-specific deployments to first live release.

Work:

- Confirm all pre-release exit criteria are satisfied.
- Pin final shared image tag across all provider releases.
- Publish launch runbook with operator checks and incident handling.

Exit criteria:

- All provider releases are green in launch environment.
- Launch checklist complete and approved.

Fallback point:

- Hold launch and revert to last known-good pre-release git state.

### Phase 5: Hardening and Onboarding Standardization

Goal: make provider onboarding repeatable and low-risk.

Work:

- Add per-provider dashboards and alerts.
- Add provider conformance test template.
- Add onboarding checklist for new providers (code + overlay + app manifest + runbook).

Exit criteria:

- New provider can be added with one adapter implementation and one overlay/app onboarding path.

## Success Metrics

### Reliability

- Pre-release gate: 3/3 successful scheduled runs per provider.
- Post-launch target: CronJob success rate per provider >= 99% over rolling 7 days.
- Post-launch target: publish success ratio to `raw-news` >= 99.5% per provider.

### Isolation

- 100% of provider-specific runs report exactly one `source_provider` value.
- 0 incidents of cross-provider secret exposure in pod env configuration.

### Data Contract Quality

- `NewsItem` contract conformance = 100% in conformance tests.
- Invalid-provider configuration failures are fail-fast and explicit (no silent fallback).

### Operability

- Failed provider release can be suspended within 10 minutes.
- Provider deploy does not require restart/redeploy of other provider releases.

## Micro-Step Execution Backlog

### Phase 0 Micro-Steps

1. Fix Helm helper include mismatch in chart templates.
2. Add a chart render check command for local validation.
3. Document canonical provider ids in code and docs.
4. Define provider overlay file layout and naming.
5. Add go/no-go checklist for each pre-release phase.

### Phase 1 Micro-Steps

6. Add provider enum/validation in runtime config loader.
7. Implement provider-to-ingestor factory map.
8. Add provider-specific required-secret validation.
9. Remove provider auto-enable behavior based on key presence.
10. Add unit tests for all provider selection and validation cases.

### Phase 2 Micro-Steps

11. Create provider overlay values files.
12. Add provider env var `PROVIDER` to ConfigMap template.
13. Add conditional secret injection in CronJob template.
14. Add CI matrix to render/lint all overlays.
15. Add release naming convention check in docs/runbook.

### Phase 3 Micro-Steps

16. Deploy first provider release in pre-release cluster and validate runs.
17. Execute failure drill for first provider (suspend + recover path).
18. Deploy second provider release and validate runs.
19. Deploy third provider release and validate runs.
20. Confirm pre-release gate metrics meet target before launch.

### Phase 4-5 Micro-Steps

21. Freeze launch image tag across all provider releases.
22. Publish launch runbook and checklist.
23. Add per-provider dashboards and alerts.
24. Publish onboarding checklist and conformance template.

## Follow-Up Actions

- Create implementation tickets for all micro-steps above.
- Add cross-reference to infra ADR-003 when this ADR is accepted.
- Update roadmap to reflect phase gates and metric targets.