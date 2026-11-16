# Timebox 4 gap analysis

See [CURRENT_STATE.md](CURRENT_STATE.md) for inspection scope and evidence limits. BE/FE/Engine prefixes identify the three local repositories. No existing end-to-end product pipeline has been verified. Priorities target a restricted, single-project demonstration; they are not a production backlog.

## Feature gaps and reuse

| Feature | Current State | Required Changes | Existing Code to Reuse | Priority | Complexity |
|---|---|---|---|---|---|
| GitHub Markdown retrieval | No product integration | Fetch chosen files at resolved commit; store exact text, source URL, hash and selected sections | BE Flask routes; Engine checkpoint/hash patterns | P0 | S |
| Requirements inventory | No product DB; contracts have a source string | Versioned source/requirement records, categories, acceptance statements and automatable/manual decision | Engine `BehaviorContract`, `ExpectedBehavior` | P0 | M |
| BRDs | No importer/parser | Accept Markdown/plain-text BRD sections with source citations; split composite requirements and ask PM to confirm | Existing strict schema/AI adapter | P0 for textual BRD; binary import P2 | S/M |
| GitHub Issues | No importer | Fetch selected issue or label-filtered issues, paginate, omit PRs, snapshot number/body/updated time | Same GitHub HTTP adapter as files | P1 | S |
| Requirement interpretation | AI infers from discovered UI | Supply requirement text as authority; quote source; output independent checks and explicit gaps | Engine `regression/expectations.py` | P0 | M |
| Map requirements to functionality | AI capabilities plus discovered graph | Requirement→flow/entry route→observations mapping, manual confirmation, unresolved mappings visible | `flow_packet`, `validate_expectation`, `FlowCandidate`, `AppGraph` | P0 | M |
| Execution integration | Engine CLI exists, BE start is placeholder | Versioned adapter, durable run, bounded local dispatch, timeout/status/restart recovery | CLI/FlowRunner/contract compiler; BE `RUN_PATH` | P0 | L |
| Functional validation | Persistence/flow checks exist separately | Validate explicit intended actions/end states and negative cases against confirmed requirements | `PersistenceRunner`, `FlowRunner`, typed `UIAssertion` | P0 | M |
| Business logic | Relational assertions and constrained API checks exist | Bind documented rules to observed values; retain preconditions, business impact and uncertainty | `Relation`, `decide`, `OutcomeCheck`, `evaluate_instance` | P0 for one case | M |
| UX/design | DOM/control/readable regression comparison | Check explicitly specified element/navigation behavior; label subjective judgments manual | `ui_differ.py`, `contract_checks.py`, evidence UI | P1 | M |
| Four-state coverage | holds/violated/inconclusive plus gaps | Persist one result per selected expectation; explicit not-tested reasons; aggregate per requirement | Engine statuses/skips, FE `StatusBadge` | P0 | M |
| Structured findings | Engine facts and AI explanations, no product rows | Requirement/result IDs, expected/actual, observations, impact, confidence, steps, evidence and recommendation | `regression/findings.py`, `interpreter.py`, `baseline/saver.py` | P0 | M |
| Screenshots/traces | Local per-flow artifacts, screenshot after cleanup | Capture at validation/failure before teardown; retain result when capture fails; artifact registry/download | `FlowRunner.run`, `observation_points.py`; FE `EvidencePane` | P0 | S |
| Video evidence | Absent | Enable recording on actual per-test context; finalize close, register video, render player | `FlowRunner.run` context lifecycle | P1 | M |
| Approx. 10-second clip | No timing/video processing | Record monotonic action/observation offsets, offer focused short run first; optional actual trimming | Existing result duration/highlight records, new offsets | P2 | M |
| Artifact storage | Local paths; BE 501 metadata/download | Local private files for local demo; durable object storage only for hosted version; stable artifact links | JSON evidence notes, existing artifact routes | P0 local / P1 hosted | M |
| PM review | Discussion is local, no decisions | Group by requirement/category, persist pending/approved/rejected, notes and reviewer/time | FE layout, expected/observed and evidence primitives | P0 | M |
| Jira creation | Absent | Server client, approved-finding gate, issue payload, durable issue ID, duplicate guard and failure recovery | BE HTTP structure; no reusable Jira-specific implementation | P0 | M |
| API error propagation | CORS and error UI exist separately | Shared JSON envelope, HTTP/client validation, request IDs, visible retry and job errors | `allow_frontend_origin`, `AsyncBoundary`, dev integration fetch | P0 | S |
| Dashboard honesty | Fixtures, static PR metadata, simulated stream | Replace core hooks, remove unsupported totals/healing and inert controls; no fallback fixtures | Existing FE pages/components, Zod and React Query | P0 | S/M |
| Product persistence | None; engine JSON plus budget SQLite | Minimal relational schema/migrations; source/run snapshots; review and Jira records | Engine serialized records and stdlib SQLite for local MVP | P0 | M |
| Authentication | Supabase browser operations; BE none | Keep scope; restricted team access, reuse existing token only if necessary for hosting | FE auth service and Supabase clients | Deferred expansion | S only if exposure requires |
| CI/integration test | FE/engine workflows separate | Add BE contract tests and one real FE→BE→engine vertical test; retain engine tests | Existing workflow/tests | P0 | M |
| Full remote CI/CD testing | No dispatch integration | Not needed for PM validation MVP | Existing workflow conventions only | Deferred | L |

Complexity: XS < half-day; S roughly 0.5–1 day; M 1–2 days; L 3–5 days; XL >5 focused person-days. Integration/debugging can exceed these ranges. Tasks overlap; do not sum this table as an independent estimate.

## Files and dependencies

- **BE**: extend `backend/main.py` only for the chosen endpoints; add small `storage.py`, `contracts.py`, `services/github.py`, `services/analysis.py`, `services/jira.py`, `jobs.py`, schema/migration and tests. These names are proposals, not existing files. No need to implement every 501 stub.
- **Engine**: adapt `regression/expectations.py`, `knowledge/contracts.py`, `runner/flow_runner.py`, `runner/observation_points.py`, reporting export and a small product adapter. Keep current CLI/regression operation working. Avoid copying implementations into empty BE modules or introducing ambiguous top-level imports between repositories.
- **FE**: replace `use-runs.ts`, `use-run-detail.ts`, selected flow hooks and fixture live hook; update run/failure/artifact schemas/mappers/types; extend `EvidencePane`, overview, and run detail; add requirement import/confirmation and finding-review components. Keep shell/forms/primitives.
- **Dependencies**: Engine already declares Playwright, Pydantic, OpenAI and Anthropic; BE does not. Package the existing engine at a pinned revision in the backend runtime rather than relying on a developer's sibling path. Local SQLite and HTTP calls can use Python stdlib; no new database service or GitHub/Jira SDK is necessary. A single small HTTP library is optional for simpler timeout/multipart handling, not an architectural requirement. Browser binaries must exist in the eventual executor environment. No packages were installed in this analysis.
- **Hosted alternative**: durable PostgreSQL (existing Supabase project only after confirming availability) and object storage need schema/setup and possibly driver/storage dependencies. Do not put authoritative SQLite/files on an ephemeral or multi-instance server. FFmpeg is optional P2 for physical trimming; it is not needed to record/replay original Playwright WebM files.

## What can actually be automated

| Category | Browser-verifiable expectation | Explicit input needed | Human judgment / unsupported scope |
|---|---|---|---|
| Functional | Submitted value survives reload; form reaches specified confirmation; search results match a known dataset | Defined action, test data, success and failure conditions | Whether feature solves the stakeholder's problem; unknown search relevance |
| Business logic | Cart cannot complete empty checkout; quantity propagates; documented totals/eligibility rules hold | Applicable policy, rounding/currency rules, roles, boundary data and side effects | Profitability, regulatory compliance, business suitability, rules invisible to browser |
| UX/design | Required control present and accessible; documented navigation route works; specified labels and states exist | Accepted design text/screenshots, viewport, route and version | “Confusing,” “beautiful,” “easy to find,” or pixel conformity with no design reference |

Do not silently substitute UI observations for specifications. A broken total is not the expected total because discovery saw it. A missing selector may mean stale mapping rather than missing functionality. Missing data, unreachable paths, absent design sources, subjective BRD statements and unknown backend effects should generate explicit gaps, not failures or passes.

## Three-stage fit

1. **Understand requirements**: import selected source, extract requirements with source anchors, PM confirms interpretation and mapping. Reuse strict AI schema and contracts; add source revisions and requirement IDs.
2. **Analyze application**: freeze selected expectation/mapping revisions, call existing discovery/compiler/runner, evaluate observed values, preserve gaps/errors. Reuse relation engine rather than asking AI to decide truth from prose alone.
3. **Generate/review findings**: persist all outcomes, explain failures with grounded AI, present evidence, save PM review, allow Jira only after approval. Requirement interpretation review and finding approval are distinct events.

## Targeted error and presentation fixes

- Legacy success responses must stop claiming saved/queued behavior until persistence/dispatch exist. Return the shared not-implemented error for unused stubs; no frontend fallback to fixtures on a failed fetch.
- Catch malformed requests and unexpected exceptions centrally; return status-appropriate JSON and a request ID, log redacted detail server-side. Preserve CORS on API errors.
- Poll persisted jobs with stage/heartbeat/last error; a completed browser execution can still have inconclusive results or failed AI explanation. Those states must remain separate.
- Show source unavailable, provider timeout/budget exhaustion, browser failure, missing evidence and Jira failure as distinct PM-facing messages with appropriate retry actions.
- Preserve approvals after Jira failure; persist ticket creation and attachment status separately. Do not automatically repeat an uncertain create request.
- Audit status/checkmark provenance rather than deleting all check icons. Clipboard success and navigation controls are real; fixture pass/healed and simulated live indicators are not proof of validation.
