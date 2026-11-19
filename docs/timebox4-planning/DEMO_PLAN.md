# Minimum viable end-to-end demonstration

## What can honestly be promised today

No complete product demonstration exists in the available source. The engine implements real discovery, execution, deterministic checks, AI expectation generation/explanation and local evidence. FE is largely fixture-backed and BE does not execute the engine. GitHub retrieval, durable product records, PM finding approval and Jira must be built.

The smallest viable product has one target environment, a small set of imported Markdown requirements, one confirmed executable expectation, one real failure finding with screenshot, persistent approval and one real Jira export. Original video is the next enhancement. Do not expand project management/authentication to support the presentation.

## Critical target-selection constraint

The repository `../blindspottest` includes `demo_app` and `demo_app/regression_fixture.py`. These intentionally plant defects: profile bio persistence, catalog string sorting, checkout omitted protection amount, etc. `demo_app/manifest.py` even exposes ground truth at `/__truth`. Those are valuable engineering regression fixtures, but **must not be the primary demonstration** under the stated prohibition on hardcoded bugs. Do not feed defect descriptions/manifest data into the model or select a finding from canned outputs.

A genuine, unseeded discrepancy in the intended BlindSpot target has not been verified in this assessment. The target's actual hosted service and GitHub business requirement were not exercised. **Pre-demo gate:** the team must identify an accessible real target, written requirement and reproducible discrepancy through actual interaction. Prefer the team's normal application build with an independently documented functional/business requirement. If “BlindSpot test application” refers to another repository/deployed app, obtain its location. If the instructor accepts seeded application defects as experimental controls, get that scope clarified; do not silently treat the current fixtures as a qualifying primary demonstration.

Until that gate passes, the plan below is executable implementation scope, not a claim that a specific genuine bug is already available. Keep a passing/inconclusive path available and report real results even if no defect is found; that alone would not satisfy the requested discrepancy demonstration.

## Demo scenario selection

Prefer a short profile/settings persistence, documented filter rule, or simple state/quantity propagation flow already supported by the engine. A total-reconciliation rule is a useful business example only when the real application has the documented rule, stable currency/data and a genuinely observed mismatch. Multi-step checkout is riskier because setup, optional branches, state and side effects complicate timing.

Use a real README/requirements Markdown section containing a precise statement with a stable ID. The team may author legitimate acceptance criteria describing intended behavior before testing, with normal product-owner confirmation; it must not write “requirements” reverse-engineered from a desired bug result. Save exact file revision. UI mapping/test setup may be confirmed manually; findings and observed values must not be hardcoded.

A requirement like “submitted profile biography is preserved after a successful save and reload” illustrates the shape, not a verified current discrepancy or selected demo requirement. Source IDs, actual values, severity and issue keys must come from the real run.

## Ten-step script and current support

| Step | Presentation action | Current support | Minimum implementation |
|---|---|---|---|
| 1 | Open selected GitHub requirement and import | None in product | T04 Contents API, immutable source text/SHA/URL; source visible in FE |
| 2 | Select corresponding application functionality | Engine graph/capability and selector validation exist | T05 requirement→flow mapping and confirmation; no truth manifest |
| 3 | Start validation and show real browser interaction | Engine `FlowRunner`/`PersistenceRunner` implement execution; BE start is fake | T06 durable run, engine adapter and polling |
| 4 | Evaluate actual observations against intended rule | Engine relations/contracts/AI expectations exist, lacking document input | T05 requirement-aware prompt + confirmed relation; T08 raw/result mapping |
| 5 | Identify genuine discrepancy | Engine can compute violated relations; no qualifying unseeded bug verified | T01 reproduction gate; actual failed outcome, never injected output |
| 6 | Read structured finding | Engine findings/interpreter and FE layout exist separately | T08 persisted requirement/category/expected/actual/impact/confidence/steps/action |
| 7 | View relevant screenshot; optional short video | Engine PNG/trace conditional, captured after cleanup; no video | T07 pre-cleanup capture + artifact service; T13 original WebM if time |
| 8 | Review result in PM dashboard | FE components show fixtures | T09/T11 real API hooks, grouping, four states, no simulated live stream |
| 9 | Approve finding and refresh page | No review functionality | T02/T09 persistent decision and server gate |
| 10 | Create Jira ticket and open real issue | None | T10 real API + evidence, stored ID/URL, duplicate protection |

P0 task set: T01–T12 from [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md). T13 provides video; T17 provides a physical ~10-second clip if mandatory. Screenshot-only P0 meets the requested screenshot-or-video demo step but does not fully meet the separate video feedback; describe that limitation explicitly.

## Exact component assembly

- **FE reuse:** AppShell, React Query, Zod mappers, `ExpectedObserved`, `StatusBadge`, `AsyncBoundary`, existing run detail and evidence pane. Build RequirementImport/RequirementConfirmation, RequirementsCoverage, FindingDetail/ReviewActions and JiraExportAction. Names are proposed components.
- **BE reuse:** Flask app, CORS, route prefixes for runs/artifacts; implement thin import/interpret/run/result/review/Jira endpoints and JSON errors. Existing 501 schemas are starting points, not finished services.
- **Engine reuse:** discovered graph/readable controls, `flow_packet`, `ExpectedBehavior`, `compile_expectations`, `BehaviorContract`, `FlowRunner`, observation points, `evaluate_instance`/`decide`, serialized results and grounded interpretation. Keep deterministic verdict independent of AI prose. Direct failed results do not require baseline/regression setup.
- **New persistence:** project/environment, versioned source/requirement/expectation, run/results, findings/artifacts, reviews, Jira export record. Local SQLite and private files suffice on a restricted single machine.
- **External prerequisites:** readable actual GitHub document, functioning selected model credential/account, existing Playwright/browser environment, authorized mutable staging target and real Jira sandbox/site/project with creation/attachment permissions. No service was connected or modified during this analysis.

## Suggested 6–8 minute presentation

1. **Intent (1 minute):** show actual GitHub requirement and frozen source revision; say what a PM wants to validate. Show its category and confirmed expectation.
2. **Execution (1–2 minutes, depends on measured runtime):** click Analyze, show real running stage and application interaction. If using a previously completed real run for timing, state when/build it was executed and keep its complete evidence; do not label replayed UI as live.
3. **Finding (2 minutes):** show expected versus observed values, requirement citation, business impact and evidence. Explain why the verdict is reliable and what remains outside tested scope.
4. **PM control (1 minute):** show pending status, approve with note, refresh to prove persistence. Optionally demonstrate rejecting a separate genuine uncertain finding only if available.
5. **Developer handoff (1 minute):** create real Jira ticket, open issue, verify description and attachment. Repeat click returns existing issue. Display no ticket before approval.

Show coverage honestly: one executed requirement is not proof the whole application meets business needs. Ideally include a real pass plus a deliberately unsupported subjective requirement reported as not tested; those are actual validation dispositions, not fake findings.

## Evidence and Jira contents

The chosen finding must include source requirement ID/text and immutable URL/revision, target/build and run time, expected and actual values, reproducible interaction steps, category, proposed severity/business impact, confidence basis, screenshot artifact and optional video interval, PM decision/note and Jira ID/URL. Evidence must show the relevant state before cleanup. Never expose target credentials or card/personal data.

For local demo, localhost evidence links are not usable by remote Jira viewers. Attach actual screenshot/video bytes to Jira, with a stable run-page link as supplementary context. If attaching fails, display “ticket created; evidence upload failed,” preserve the issue key and retry upload without creating another ticket. Expiring signed artifact URLs are not permanent Jira evidence.

## Rehearsal acceptance checklist

- Independently reproduce the real discrepancy at least twice; source requirement was confirmed without using planted defect ground truth.
- Import from actual GitHub and make at least one real model call. Exact model-cache reuse is labeled if used; no fallback to canned finding.
- Run actual Playwright, confirm observed values and screenshot/video match that run and selected requirement.
- Verify passing, failed, inconclusive and not-tested semantics with meaningful tests; demo only claims states actually observed.
- Reload FE and restart BE: completed result/review/export persist. Interrupted jobs show interrupted/error rather than endless live animation.
- Before approval, direct Jira-export request is refused. After approval, one actual issue is created; repeated or concurrent click does not duplicate it.
- Simulate dependency failures only in engineering tests; the presentation uses actual integrations. Rehearse understandable source/model/browser/Jira error messages.
- Measure run/video duration. A full recording with a highlighted interval is not described as a trimmed ten-second clip.
- Two clean end-to-end rehearsals pass before feature freeze.

## Honest contingency

If an external service is down during the presentation, show a previous **real** run and its timestamp, evidence and actual Jira issue, then show the live failure state. This demonstrates retained evidence, not live integration success. A recording can supplement the live presentation but does not replace implementation acceptance. If no genuine discrepancy is available, report that blocker and agree a revised demonstration with the instructor; do not manufacture bugs or findings.
