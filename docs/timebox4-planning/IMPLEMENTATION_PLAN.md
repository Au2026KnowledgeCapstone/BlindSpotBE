# Timebox 4 implementation plan

## Outcome and assumptions

Deliver one real requirements-based validation path: GitHub requirement → confirmed expectation → existing Playwright engine → observed discrepancy and evidence → persistent PM approval → real Jira issue. No fixtures or planted-bug manifest in this path.

Assume three contributors, approximately 10 working days each, a restricted local demonstration, one selected target application and one Jira project. Team size/deadline are unknown, so these are planning assumptions, not commitments. XS < half-day; S 0.5–1; M 1–2; L 3–5; XL >5 focused person-days. Estimates include focused task tests; reserve separate integration/rehearsal time. P0 is roughly 17–25 person-days plus 4–6 integration/contingency days; P1 adds roughly 4–7. With three contributors, budget about 2–3 weeks at meaningful availability, more at typical part-time student capacity. Re-estimate after the engine adapter spike; do not promise every P1/P2 item inside a short timebox.

No changes in this plan have been implemented. BE/FE/Engine refer to repositories defined in [CURRENT_STATE.md](CURRENT_STATE.md). Proposed filenames below are new files to create later. Detailed contracts are in [PROPOSED_ARCHITECTURE.md](PROPOSED_ARCHITECTURE.md).

## Ordered task index

| ID | Task | Priority | Size | Depends on | Suggested owner |
|---|---|---|---|---|---|
| T01 | Freeze demo scope, integration contract and real discrepancy | P0 | S | Team target/access decisions | All; one coordinator |
| T02 | Persist sources, requirements, runs, results, reviews and exports | P0 | M | T01 | Backend |
| T03 | Establish JSON errors and frontend API client | P0 | S | T01 contract | Backend + frontend |
| T04 | Import GitHub Markdown/text BRD requirements | P0 | S | T02, T03 | Backend |
| T05 | Ground and confirm expectations against requirements | P0 | M | T01, T02, T04 | Engine |
| T06 | Package engine adapter, execute and expose durable run status | P0 | L | T01, T02, T03; T05 to finish | Engine + backend |
| T07 | Capture relevant screenshots/traces and serve artifacts | P0 | S | T06 interface | Engine |
| T08 | Persist four-state results and grounded findings | P0 | M | T05, T06; T07 for evidence | Engine + backend |
| T09 | Build PM import, coverage, evidence and review UI | P0 | M | T01 contract; T04–T08 for integration | Frontend |
| T10 | Export approved finding to real Jira safely | P0 | M | T02, T03, T08, review API from T09 | Backend |
| T11 | Remove misleading capabilities and align product schemas | P0 | S | T03, T09 | Frontend |
| T12 | Verify vertical path and rehearse from clean state | P0 | M | T04–T11 | All |
| T13 | Record original per-test video and display it | P1 | M | T06, T07, T09 | Engine + frontend |
| T14 | Add selected GitHub Issues import | P1 | S | T04 | Backend |
| T15 | Add explicit design/navigation check and negative business case | P1 | M | T05–T09; approved specs | Engine + frontend |
| T16 | Prepare durable hosted execution, only if required | P1 conditional | L | Hosting decision, T02, T06, T07 | Backend |
| T17 | Physical ~10-second evidence clips | P2 | M | T13, verified video offsets | Engine |
| T18 | Binary BRD/design import | P2 | M/L | T04, sample formats/access | Backend |
| T19 | Cross-run duplicate suggestions and review filters | P2 | M | T08–T10 | Backend + frontend |

T16 is additional scope outside the local estimate. If hosting is mandatory, treat it as a P0 dependency and cut other work. If exact short video is mandatory, elevate T13/T17 similarly. Do not silently omit a grading requirement.

## Task specifications

### T01 — Freeze the demo and contract

**Description:** establish evidence of a genuine discrepancy before committing presentation claims. **Priority/size:** P0/S. **Dependencies:** accessible intended target, team requirement owner. **Files:** planning decisions, proposed shared API examples; inspect target source without modifying behavior.

**Steps:** choose one repository document and one bounded functional or business-logic flow; manually execute its intended behavior; record expected/observed values and target version; exclude known seeded `/broken` defects; agree v1 fields/status semantics, local versus hosted boundary, Jira Cloud/project and team ownership. Spike how Engine is imported without top-level `knowledge`/`runner` module collisions.

**Acceptance:** real source requirement and reproducible discrepancy identified, or explicit blocker recorded with owner; target accessible and approved for mutations; no dependence on `/__truth`; one agreed FE/BE example for queued/completed/error and four result states. **Testing:** repeat manual reproduction twice with reset data; review the proposed engine invocation/import in a clean runtime later. If no defect is found, narrow target/search; do not create a fake one.

### T02 — Minimal durable product schema

**Description:** preserve intent, results, decisions and Jira IDs across refresh/restart. **Priority/size:** P0/M. **Dependencies:** T01. **Files:** new BE `storage.py`, schema/migrations, repository methods and tests; later add deployment DB driver only if needed.

**Steps:** implement tables from architecture, FK enforcement, uniqueness and snapshot fields; initialize one real project/environment through an explicit setup path; transactionally save run + selected result inventory and export claims; add version checks for review; separate engine budget DB. Use stdlib SQLite locally, not a replacement for ephemeral cloud persistence.

**Acceptance:** source/expectation edits cannot alter prior run snapshots; review and export survive process restart; duplicate run/export keys resolve to one row; invalid associations fail. **Testing:** isolated temporary DB migration/rollback, foreign-key, uniqueness, stale-review and restart tests. No live production database writes in automated tests.

### T03 — End-to-end error contract

**Description:** make backend failures useful in the UI. **Priority/size:** P0/S. **Dependencies:** T01 contract. **Files:** BE `backend/main.py`, proposed `errors.py`, `tests`; FE proposed `shared/api/client.ts`, `AsyncBoundary.tsx`, `InlineError.tsx`, dev integration page.

**Steps:** handle validation/HTTP/unexpected exceptions with JSON status/code/message/request ID; redact logs; preserve CORS; make unused legacy success stubs report unavailable; add FE status/timeout/schema/error parsing and safe retry behavior; never substitute fixtures on failure.

**Acceptance:** malformed JSON, missing fields, unknown resource, dependency timeout, 501 and unexpected exception produce readable messages; inputs remain on failed submission; no secrets/stack traces sent to FE. **Testing:** Flask client tests including CORS on errors; FE request-double tests for JSON and non-JSON errors, timeouts and schema mismatch. Existing CORS suite must run in a prepared environment without changing semantics.

### T04 — GitHub source and textual BRD import

**Description:** import actual documented intent. **Priority/size:** P0/S. **Dependencies:** T02/T03. **Files:** new BE `services/github.py`, requirement import routes/storage/tests; FE import form.

**Steps:** accept owner/repo/path/ref, resolve file revision, bounded Contents API retrieval and text decode; store source snapshot/hash/URL; allow PM section selection; support text/Markdown BRD with same provenance model. Keep token server-side and initially use public content when possible.

**Acceptance:** requirement source view shows actual GitHub URL, frozen revision and text; importing same revision is deduplicated; private access failure is explicit; a BRD section can be represented without binary processing. **Testing:** HTTP-double tests for missing file, rate limit, large/binary response, bad ref and authorization; one read-only real import in team rehearsal. No external writes required.

### T05 — Requirement-aware AI expectations and confirmation

**Description:** extend existing structured expectation generator, preserving deterministic execution. **Priority/size:** P0/M. **Dependencies:** T01/T02/T04. **Files:** Engine `regression/expectations.py`, `knowledge/contracts.py`, product adapter; BE interpretation service/routes; FE confirmation view.

**Steps:** add requirement ID/revision/text/citations to packet and schema; map selected discovered flow or allow manual selection; generate typed allowed observations/relations plus support/gaps; validate source and graph references; persist drafts and PM-confirmed revisions; prevent inference from UI replacing documented business intent.

**Acceptance:** known requirement yields a source-linked expectation or explicit gap; unknown selector/unsupported arithmetic/nonexistent source is rejected; ambiguous subjective requirement remains manual/not tested; PM can confirm without editing code. Existing generation path remains usable. **Testing:** prompt packet/schema and reference-validation tests with model doubles; one real provider call against the chosen requirement during rehearsal; repeat after a changed requirement revision to verify snapshot isolation.

### T06 — Engine integration and bounded job lifecycle

**Description:** connect Flask to the implemented engine without rewriting it. **Priority/size:** P0/L, highest integration uncertainty. **Dependencies:** T01/T02/T03, T05 for actual execution input. **Files:** Engine product adapter/package metadata as needed; BE `services/analysis.py`, `jobs.py`, `backend/main.py`; FE run hooks/schemas.

**Steps:** pin engine revision/package; run discovery/compile/execution with selected expectation IDs and target; use a versioned serializable result envelope; persist and claim queued job before execution; execute outside request using one bounded executor; update stages/heartbeat/results; bound time/actions/model calls; poll authoritative status; recover abandoned jobs after restart. Avoid debug reloader, background fork duplication or unbounded subprocess input. Use explicit argv if CLI bridging is chosen.

**Acceptance:** POST returns 202 promptly after persistence, repeated idempotency key returns same run, polling shows real progress and terminal state; engine exceptions/timeouts become persisted run error with partial results retained; restart does not show a permanently live run; only allowlisted targets execute. **Testing:** fake adapter for lifecycle contract tests, one real browser integration, crash/timeout and duplicate-start tests; fresh-runtime package import check. Check actual Engine exit codes—1 may represent a finding and 2 incomplete execution, not blanket transport failure.

### T07 — Screenshot/trace evidence at the relevant state

**Description:** capture genuine evidence tied to a result. **Priority/size:** P0/S. **Dependencies:** T06 interface. **Files:** Engine `runner/flow_runner.py`, `runner/observation_points.py`, export adapter; BE artifact storage/routes; FE existing evidence pane.

**Steps:** capture before teardown at evaluated observation/failure; preserve original trace; record run/result/action IDs, hashes and MIME; contain capture/trace errors; serve by opaque artifact ID, not arbitrary filesystem path; choose local private folder for local demo.

**Acceptance:** screenshot shows relevant UI/values and survives restart; selected finding opens its own artifact; failed capture does not erase deterministic result; absent evidence is labeled. **Testing:** browser test comparing screenshot timing to cleanup, invalid artifact/path/access tests, real image/trace readability. Existing post-cleanup screenshot behavior should be covered by a meaningful regression test.

### T08 — Four-state coverage and grounded findings

**Description:** turn execution records into PM-readable requirement validation. **Priority/size:** P0/M. **Dependencies:** T05/T06/T07. **Files:** Engine adapter, `knowledge/flows.py` mapping only as needed, `regression/interpreter.py`; BE result/finding storage and routes; FE schemas/mappers.

**Steps:** materialize selected inventory; map raw verdicts/gaps to four states; retain partial/error reasons; aggregate conservatively; derive failed findings from actual observed mismatches, including existing violations without a passing baseline; add AI explanations citing only stored requirement/result/artifact IDs and business impact.

**Acceptance:** no requirement passes from an empty check list; engine failure is inconclusive/error, not business bug; all results show expected/actual or an unavailable reason; explanation failure leaves result and evidence intact; confidence has a stated interpretation basis. **Testing:** status/aggregation truth table, missing/unsupported/mixed checks, existing violation, stale mapping, fabricated AI reference and provider timeout; one real explanation with verified observations.

### T09 — PM dashboard, confirmation and review

**Description:** make requirements and decisions the primary interface. **Priority/size:** P0/M. **Dependencies:** T01 contract allows UI development; T04–T08 for completion. **Files:** FE overview/run-detail/flow pages and hooks; new `features/requirements` and `features/findings` components; BE review route/storage.

**Steps:** import/select requirements; show draft interpretation/mapping confirmation; start validation; poll stages; show four-state coverage grouped by requirement/category; reuse expected/observed and evidence components; add approve/reject + note + pending state; save review version/time and reviewer label; expose Create Jira only after saved approval.

**Acceptance:** browser refresh restores real results/reviews; rejected or pending findings cannot create tickets through UI or API; filters do not hide untested requirements; save errors remain visible; no fixture-backed fallback. **Testing:** component tests for all outcomes/reviews/loading/errors and stale version; API-backed browser path with real persisted result; keyboard-accessible review controls.

### T10 — Jira approved finding export

**Description:** complete the business-to-developer handoff. **Priority/size:** P0/M. **Dependencies:** T02/T03/T08 and review API T09. **Files:** BE `services/jira.py`, export routes/storage/tests; FE finding ticket action/status.

**Steps:** validate real Jira site/project/issue type/required fields and credential; create ADF description from reviewed finding snapshot; claim unique export; persist issue ID/key/URL; attach screenshot and later video, with separate attachment retries; mark uncertain create outcomes unknown for reconciliation; enforce server approval gate.

**Acceptance:** one real Jira issue contains requirement/source, expected/actual, steps, business impact and evidence; repeat click/concurrent request returns same issue; pending/rejected export blocked; attachment failure preserves issue; lost response never triggers blind duplicate creation. **Testing:** provider-double tests for 400/401/403/429/5xx/timeouts, concurrent claims, approval changes and create-success/attachment-failure; one explicitly authorized sandbox Jira create during implementation/rehearsal and repeated click verification. No Jira writes were performed in this planning task.

### T11 — Dashboard truth and schema cleanup

**Description:** remove capability claims unsupported by actual records. **Priority/size:** P0/S. **Dependencies:** T03/T09. **Files:** FE `OverviewCounters`, `RegressionsFirst`, `app-shell`, `use-live-run-events`, `run-header`, `run-detail-content`, `evidence-pane`, flow detail/editor and environment cards; shared status schemas.

**Steps:** replace fixture status/metrics/simulated emitter in core product path; omit static PR/deployment/baseline/cost/healing claims; wire or disable rerun/download; hide local comments/scheduling/policy claims until real; distinguish draft saved from executable queued; use actual observed URLs and optional click coordinates.

**Acceptance:** every completion icon/metric/evidence item in the demonstration traces to real stored data; unsupported controls state unavailable; no static last-passing calculation. **Testing:** focused rendering tests and source audit for fixture imports in production hooks; manual blank/new/error-run review. Keep valid clipboard success acknowledgment.

### T12 — Integrate and rehearse the real vertical path

**Description:** prove user value and recoverability. **Priority/size:** P0/M plus 4–6 person-day shared contingency allowance. **Dependencies:** T04–T11. **Files:** new BE integration tests, FE `e2e` spec/workflow, Engine compatibility tests; update execution instructions only when implementation is authorized.

**Steps:** prepare sandbox data and real source; run GitHub import→confirmation→browser→PM approval→Jira; include passing/inconclusive/not-tested control cases; restart and repeat; add contract gates to existing CI; capture only genuine artifacts. Tighten current FE demo-path test, whose conditional checks can skip expected interactions.

**Acceptance:** two clean end-to-end rehearsals against actual behavior; reload preserves state; no ticket before approval; one Jira ticket after repeat click; network/provider errors produce understandable states; no seeded finding/fixture output in core path. **Testing:** automated local end-to-end with external API doubles for CI, plus live GitHub/model/Jira acceptance rehearsal. CI doubles are test isolation, never the presentation's integration.

### T13 — Original per-test video

**Description:** add browser evidence with minimum infrastructure. **Priority/size:** P1/M. **Dependencies:** T06/T07/T09. **Files:** Engine inner `FlowRunner.run` context, offset records/adapter; BE artifact types; FE `EvidencePane` video element; Jira attachments.

**Steps:** enable recording on actual execution context, fixed viewport, finalize after close even on error, store offsets/file association, render controls and highlighted interval; attach original video where allowed. Prefer a genuinely short focused interaction, without promising every flow is 10 seconds.

**Acceptance:** actual selected finding has playable WebM from its run; failures still finalize evidence; player displays actual duration; longer videos are labeled full recording with interval; screenshot fallback explicit. **Testing:** browser crash/normal close, MIME/playback/seeking, isolated contexts, attachment-size policy and offset alignment.

### T14 — Selected GitHub Issues

**Priority/size:** P1/S. **Dependencies:** T04. **Files:** GitHub service/import form/source schema. **Steps:** fetch chosen issue or bounded label-filtered list, exclude pull requests, capture issue URL/body/updated timestamp/hash, reuse extraction. **Acceptance:** selected real issue becomes immutable source snapshot, later edits do not alter old runs. **Testing:** pagination/PR filtering/rate-limit/mutable-revision cases and one read-only team issue import.

### T15 — Bounded design and extra business coverage

**Priority/size:** P1/M. **Dependencies:** T05–T09 plus accepted designs/policies. **Files:** expectation generator, contract checks, optional UI-diff adapter, requirement/evidence UI. **Steps:** add one explicit missing-control/navigation expectation and one negative business-rule test with known data; state design viewport/reference/version; route subjective comments to manual review. **Acceptance:** three categories can be represented honestly, with only supported checks automated. **Testing:** sound/violating/ambiguous controls, known negative case, intentional UI change not automatically labeled defect. No pixel-perfect or universal UX claims.

### T16 — Hosted durability if required

**Priority/size:** conditional P1/L, becomes P0 if remote hosting is mandatory. **Dependencies:** early deployment decision, T02/T06/T07. **Files:** BE storage/executor configuration, migrations, artifact adapter and deployment configs; FE API base URL. **Steps:** select durable DB/object storage and continuously running execution model; remove reliance on ephemeral SQLite/local artifacts and scale-to-zero threads; implement claims/recovery and signed access. **Acceptance:** completed evidence/reviews survive instance replacement; no duplicate execution across processes; frontend can fetch artifacts; documented startup command matches chosen runtime. **Testing:** restart/instance replacement, interrupted lease, storage failure, CORS and deployed browser smoke test. Do not add a queue by default.

### T17 — Physical clip export

**Priority/size:** P2/M. **Dependencies:** T13. **Files:** proposed evidence-processing helper and artifact schema. **Steps:** optional FFmpeg after recording, approximate 10-second window around observed event, clamp start/end, retain original and provenance, attach clip independently. **Acceptance:** downloaded clip plays and shows the actual event with context; processing failure keeps full video. **Testing:** event near beginning/end, long/no-video/failed encoder, codec/keyframe playback. New dependency: FFmpeg executable; no separate processing service.

### T18 — Binary BRDs/design assets

**Priority/size:** P2/M–L. **Dependencies:** T04, actual supplied formats. **Files:** source extraction service/UI. **Steps:** support one required format with bounded parser, page/section provenance and PM extraction confirmation; OCR only if essential. **Acceptance:** extracted text traceable to original; uncertain tables/images flagged. **Testing:** representative real samples, malformed/oversized/scanned files. Parser/OCR dependencies selected only after sample review; no generic document-ingestion project.

### T19 — Duplicate suggestions and review convenience

**Priority/size:** P2/M. **Dependencies:** T08–T10. **Files:** finding/export query service and dashboard. **Steps:** compute requirement+expectation+target+observation fingerprint; suggest existing cross-run issues, keep manual confirmation; add review filters. **Acceptance:** repeats can link to an existing ticket without suppressing distinct failures. **Testing:** same/different requirement revision, different root symptom and already-rejected finding. Per-finding Jira uniqueness remains P0 independent of this enhancement.

## Parallel work and delivery gates

- **First 1–2 days:** all agree T01 contract; Backend starts T02/T03; Engine spikes adapter and mapping; Frontend builds states/review against agreed contract using test doubles in development, never claiming real execution. GitHub/Jira access requests happen now, not at the end.
- **Next 3–5 days:** Backend T04 and Jira payload spike; Engine T05–T08; Frontend T09/T11. Split `backend/main.py` ownership to avoid conflicts; services can be separate files. Use small shared schema examples before independent implementation.
- **Next 2–3 days:** connect real run/results/artifacts; finish Jira gate/export and error paths. Start T13 only after screenshot-backed vertical path exists.
- **Final 2 days or more:** freeze new scope, T12 rehearsals and fixes. P1/P2 work stops if P0 acceptance is incomplete.

Gates: G1 genuine target/requirement + approved deployment boundary; G2 real GitHub import and source-linked expectation; G3 actual browser outcome + screenshot persisted and visible; G4 approval + one real Jira issue; G5 repeat/restart/error-path verification. A failed G1 means the promised genuine discrepancy demonstration remains blocked, not permission to substitute a hardcoded defect.

## Deferred deliberately

Full authentication/RBAC/multi-tenancy; GitHub OAuth app/webhooks/PR checks; arbitrary-site autonomous testing; full BRD OCR; Figma integration/pixel-perfect visual engine; automatic healing; notifications/SSE/comments; USD billing dashboards; full regression-management UI; unrestricted production mutations; distributed workers/queues; automatic Jira creation or two-way Jira sync. Keep existing working engine capabilities, but do not expand the UI around them before the PM workflow is complete.
