# Open questions, decisions and risks

These are team/instructor decisions, not reasons to begin a rewrite. Proposed defaults permit work on contracts/UI while access decisions are resolved. No answer, credentials or infrastructure access is assumed.

## Decisions that block the corresponding implementation or demo

| Question | Why it matters / blocked work | Proposed default | Owner / timing |
|---|---|---|---|
| What is the exact Timebox 4 deadline, number of contributors and weekly capacity? | Determines whether P0 plus video is realistic | Three contributors, about 2–3 weeks of meaningful availability; reduce scope if shorter | Team lead, day 1 |
| Does “BlindSpot test application” mean `blindspottest/demo_app`, or a different real target/repository? | Current demo app intentionally seeds its defects; no qualifying unseeded discrepancy verified | Select genuine target/build and real requirement before promising failure demo | Team/instructor, day 1; blocks T01/demo acceptance |
| Will instructor accept intentionally seeded target defects, despite the primary-demo constraint? | Current `/broken` app can support engineering tests but conflicts with the requested primary demonstration | Do not use it as primary unless scope explicitly changes; never feed `/__truth` to AI | Instructor, before choosing scenario |
| Which GitHub repo/ref/path or Issue is authoritative for business intent? Is it readable? | Blocks real import and requirement semantics | One public Markdown file at resolved commit first, then selected Issues | PM/source owner, day 1 |
| Who confirms requirement interpretation, test data and business rules? | Ambiguous intent cannot become reliable failure/pass | A named team PM confirms expectation and flow mapping before execution | PM/team, before T05 acceptance |
| Is a restricted local demo acceptable, or is persistent hosted execution required? | Determines DB/storage/executor choice and adds several days | Local one-process demo; do not put SQLite/thread jobs on ephemeral multi-instance cloud | Team/instructor, day 1; blocks final T02/T06 deployment choice |
| Is an actual ~10-second downloadable video mandatory, or are screenshot/full video with highlighted interval acceptable initially? | Elevates video/trimming from P1/P2 and requires timing/processing work | P0 screenshot; P1 original per-test recording; physical trimming only if required | Instructor, day 1 |
| Is Jira Cloud or Data Center used, and which site/project/issue type/required fields are available? | Cloud v3 proposal may not match Data Center; live ticket creation blocked without permissions | One Jira Cloud sandbox integration identity; verify attachment settings and limits early | Jira owner, day 1–2 |
| Which existing model provider/account has working access and budget? | Code defaults/SDK declarations do not prove access; real AI generation blocked | Select one verified provider/model already supported by adapter; keep bounded calls and no hidden retries | Engine owner, day 1–2 |
| Is target execution allowed to save/edit/delete/place test orders, and how is state reset? | Existing engine performs actual mutations; scenario validity depends on repeatable fixtures | Approved staging target with disposable session-scoped data and small limits | Target owner, before any real execution |
| How will engine code be versioned with BE? | Import/package mismatch could block deployment and tests | Pin existing Engine as package/checked-out dependency in one runtime; don't copy modules or assume sibling path | Backend/engine owners, adapter spike |

Do not request secret values in planning documents. Integration owners should provision them through the selected runtime's existing secret mechanism during authorized implementation.

## Decisions that can be deferred

| Question | Recommendation until needed |
|---|---|
| BRD format: Markdown/text, PDF, DOCX, scan? | Treat BRD business content as textual requirements first; binary/OCR only after actual samples and need. |
| Design source: Markdown checklist, accepted screenshot, Figma? | Support explicit control/navigation expectations; mark aesthetic/design judgment manual without references. No Figma integration initially. |
| Which severity taxonomy maps to Jira? | Use low/medium/high plus business impact; configure Jira priority mapping, don't assume custom fields. |
| Reviewer identity/audit needs? | Named reviewer in restricted demo, mark identity limitations. Retain existing Supabase login; no roles/onboarding expansion. Public access requires a gate before mutation APIs. |
| How long should evidence/source/model caches be retained? | Proposed seven-day artifact retention locally; preserve source/run/review metadata. Revisit hosted/privacy policy with target owner. |
| Need cross-run Jira deduplication or two-way status sync? | Per-finding duplicate protection first; cross-run suggestions P2; Jira synchronization deferred. |
| Need SSE, notifications, comments, schedules or cost reporting? | Poll runs and focus PM decisions; hide current misleading UI instead of implementing all stubs. |
| Need automatic requirement→UI mapping for every application? | Manual confirmation/selection is acceptable for MVP; unsupported requirements remain visible. |
| How are intentional implementation changes handled? | New requirement/expectation revision and explicit rerun; old snapshots retained. No automatic baseline promotion. |
| Should all categories be deeply automated for final presentation? | Represent all three; demonstrate one reliable flow first, add explicit design/negative cases P1. Do not claim subjective UX validation. |

## Risk register and practical mitigations

| Risk / evidence | Consequence | Practical mitigation / simpler alternative |
|---|---|---|
| Ambiguous or composite business requirements | AI produces a plausible but wrong oracle | Split atomic acceptance statements, preserve exact quote and assumptions, PM confirms; unsupported subjective statements stay not tested. |
| Requirements inferred from broken UI | Implementation becomes its own specification | Feed authoritative source separately from observed controls; source-linked expectation review before execution. |
| AI hallucination/classification errors | False defect/business impact | Keep typed selector/relation validation and deterministic verdicts; validate finding IDs/evidence; show interpretation confidence and PM review. |
| Mapping unsupported controls/frames | Unreliable selectors or skipped flow | Reuse discovered paths and allow manual mapping; current expectation generator rejects frame observations without discovered frame evidence. Narrow MVP rather than invent support. |
| Crawler misses branches/limited budget | False sense of full application coverage | Show graph/requirement gaps and skipped reasons, bound scope to one flow; never infer branch correctness from absence. |
| Browser state/timing flakiness | False failure or inconclusive results | Fixed test data, isolated contexts, explicit readiness and observed paths; classify missing evidence as inconclusive, not defect; repeat selected real scenario. |
| Cleanup affects evidence and subsequent runs | Screenshot misses problem or shared state contaminates results | Capture before teardown, keep cleanup failure distinct, stop/mark run after failed restoration. Use disposable test data. |
| Trace/video capture throws | Valid verdict lost or evidence absent | Contain artifact exceptions, finalize context/video independently, persist capture error; screenshot is minimum fallback. |
| Video duration/storage/processing | Slow development, large files, broken links | Per-test original WebM, bounded resolution/retention; highlighted interval before FFmpeg; private local files for local demo, durable objects for hosted. |
| Model account/version/budget unavailable | Real AI demo fails | Verify one supported configured adapter/model early; reuse exact cached real outputs only with honest provenance; do not replace with canned findings. |
| Long-running request/server restart | Stuck UI or lost run | Persist-before-dispatch, background bounded execution, polling/heartbeat, total deadline and startup reconciliation. Avoid cloud background-thread assumptions. |
| Product database not present | Reviews/results disappear or duplicates created | Minimal migrated relational schema first; constraints and snapshot tests; leave engine budget ledger separate. |
| FE/BE schemas differ | Null parsing failures or wrong statuses | Agree versioned v1 examples and update schemas/mappers together; remove fixture fallback and fabricated defaults. |
| Jira credential/required field/rate limit | Last demo step fails | Check sandbox project metadata/access early, finite timeouts and actionable errors; approval retained for retry. |
| Jira remote success/local timeout | Duplicate ticket | Unique export claim plus operation marker; unknown state reconciled before retry, attachment failure never recreates issue. Exactly-once delivery is not promised. |
| Local artifact URL in Jira | Developers cannot see evidence | Upload actual attachment; stable review link supplementary. Don't use localhost or expiring signed link as sole evidence. |
| Missing design specification | Unverifiable UX/design claim | Ask for explicit expected controls/layout/viewport; support DOM/navigation rules first; subjective issues need human evaluation. |
| Existing UI falsely implies protection/auth/healing | Demo overstates capability or exposes mutable target | Remove unsupported claims, restrict demo access/targets, keep existing login code without prioritizing new auth features. |
| Public arbitrary target execution | Unauthorized mutations/network access | Only approved staging URLs/redirects; bounded execution and access gate. Do not generalize to an open testing service in Timebox 4. |
| Separate repos/import naming | Engine works in CLI but fails under Gunicorn | Pin dependency and test clean-runtime imports early; one adapter, no wholesale copying into BE placeholders. |
| Runtime/deployment mismatches | Working local run fails after hosting | Pick one Python/deployment runtime; verify browser OS dependencies and package versions; App Engine/Cloud Run configs are alternatives, not interchangeable proof. |
| No unseeded discrepancy found | Cannot meet requested failure demonstration | Gate scenario selection early; inspect legitimate target behavior against independently defined requirement; report blocker, don't plant bug or invent finding. |
| Semester/time constraint | Broad features prevent completion | Finish GitHub→one requirement→real evidence→review→Jira first; drop P2 and conditional hosting; reserve integration/rehearsal time. |

## Scope that is too ambitious for this timebox

Universal autonomous business validation, subjective UX scoring, pixel-perfect arbitrary design comparison, broad binary/OCR BRDs, multi-tenant integrations, comprehensive authentication, production mutation safety, cloud distributed execution, self-healing, and complete regression/cost/notification dashboards exceed the narrow MVP. The simpler alternative is a bounded, PM-confirmed requirement set with transparent coverage and real evidence—not broader unsupported claims.

## Evidence still required from the team

Successful backend/engine/FE test runs in a prepared environment; actual model credentials/account availability; authoritative remote GitHub requirement; real intended target/build and reproducible non-seeded discrepancy; Jira sandbox creation/attachment permissions; remote deployment/Cloud Build state; Supabase product tables/access policy if hosted persistence is chosen. These were not established by local source inspection.
