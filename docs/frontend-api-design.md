# BlindSpot API reference

Use this to connect [backend/main.py](../backend/main.py) to BlindSpotFE. **These are intended behaviors:** original handlers are placeholders; added handlers return `501`. FE currently uses fixtures/local state. Database, auth validation, execution and streaming still need implementation.

Path shorthand:

- `P` = `/api/projects/<project_id>`
- `E` = `/api/projects/<project_id>/environments/<environment_id>`
- `R` = `/api/projects/<project_id>/environments/<environment_id>/runs/<run_id>`

## APIs and frontend callers

“Missing” means the frontend control/component still needs building. Internal APIs are called by services, never directly by FE.

1) **`GET /`**
    **Purpose:** Return server health.
    **Called from / displayed in:** Monitoring; no application UI.

2) **`POST /api/create-project`**
    **Purpose:** Create a project.
    **Called from / displayed in:** Missing creation form; refresh [Projects][projects] and header selector.

3) **`POST /api/dashboard`**
    **Purpose:** Legacy placeholder; preserve during transition.
    **Called from / displayed in:** Use GET dashboard below for Overview.

4) **`POST /api/accounts`**
    **Purpose:** Legacy account placeholder; behavior undefined.
    **Called from / displayed in:** No caller; login/signup already use Supabase.

5) **`POST /api/environments`**
    **Purpose:** Save environment; return stable ID and configuration.
    **Called from / displayed in:** [EnvironmentCards → New environment → Create][env].

6) **`POST /api/projects/<project_name>`**
    **Purpose:** Legacy flow-list placeholder.
    **Called from / displayed in:** Use GET `P/flows` instead.

7) **`POST /api/projects/<project_name>/flows/<flow_id>`**
    **Purpose:** Legacy flow-detail placeholder.
    **Called from / displayed in:** Use GET flow detail instead.

8) **`POST /api/projects/<project_name>/run-test`**
    **Purpose:** Save and queue a run of an existing flow; return new ID/number/status.
    **Called from / displayed in:** Missing Run button on existing flow; navigate to run detail.

9) **`GET /api/projects`**
    **Purpose:** List projects accessible to the user: ID and display name.
    **Called from / displayed in:** [Projects page][projects] and [AppShell project dropdown][shell].

10) **`GET /api/environments?project_id=...`**
    **Purpose:** List the project's environments.
    **Called from / displayed in:** [Header environment dropdown][shell] and [environment cards][env].

11) **`GET /api/environments/<environment_id>`**
    **Purpose:** Return name, kind, base URL, note, credential reference and policy.
    **Called from / displayed in:** [Environment cards/details][env]; full details UI missing.

12) **`GET P/credential-references`**
    **Purpose:** List credential IDs/names; never return secrets.
    **Called from / displayed in:** [Credentials reference field][settings]; environment form selector missing.

13) **`GET P/execution-policies`**
    **Purpose:** List available policies, allowed modes and limits.
    **Called from / displayed in:** Missing policy selector in environment form.

14) **`GET P/flows?environment_id=...`**
    **Purpose:** List existing flows with name, feature area, last status/time and recent status history.
    **Called from / displayed in:** [FlowsList][flows], via `useFlows`.

15) **`GET P/flows/<flow_id>?environment_id=...`**
    **Purpose:** Return configured steps/settings, revision and recent runs.
    **Called from / displayed in:** [FlowDetailContent → Configured Steps][flow]; settings/history sections need adding.

16) **`GET /api/dashboard?project_id=...&environment_id=...`**
    **Purpose:** Return execution counts, pass rate, weekly AI cost, seven-day trend, active regressions and latest five runs.
    **Called from / displayed in:** Overview: [OverviewCounters][counts], [RegressionsFirst][regressions], [RecentRunsTable][recent]. Trend chart missing.

17) **`GET E/runs`**
    **Purpose:** Return latest five run summaries, newest first; allow older pages and filters.
    **Called from / displayed in:** [RunsContent table][runs], via `useRuns`.

18) **`GET R`**
    **Purpose:** Return run summary, saved execution configuration and actual baseline run references.
    **Called from / displayed in:** [RunHeader][header] and [FailureSummary][failure], via `useRunDetail`.

19) **`POST R/reruns`**
    **Purpose:** Create a new run from an existing run; return new ID/number/status.
    **Called from / displayed in:** [RunHeader → Re-run][header]; currently an alert.

20) **`GET R/steps`**
    **Purpose:** Return ordered executed steps and their results.
    **Called from / displayed in:** [StepsPane][steps], left column of run detail.

21) **`GET R/steps/<step_id>/actions`**
    **Purpose:** Return ordered actions, results, click coordinates and screenshot associations.
    **Called from / displayed in:** [ActionRow][actions] under each step; selection updates evidence.

22) **`GET R/failures`**
    **Purpose:** Return expected/observed, defect vs agent error, likely cause, next steps and evidence links.
    **Called from / displayed in:** [FailureSummary][failure] and [AI analysis tab][analysis].

23) **`GET R/artifacts`**
    **Purpose:** List screenshot/before-after/log/trace metadata and step/action associations.
    **Called from / displayed in:** [EvidencePane][evidence] thumbnails/images; trace selection.

24) **`POST R/artifacts/<artifact_id>/download`**
    **Purpose:** Authorize access and return a temporary download URL.
    **Called from / displayed in:** [EvidencePane][evidence] image sources and [Download trace][header].

25) **`GET R/logs?kind=console|network`**
    **Purpose:** Return paginated, redacted logs; support selected action/step context through associations.
    **Called from / displayed in:** [ConsoleTab][console] and [NetworkTab][network].

26) **`GET R/ai-usage`**
    **Purpose:** Return per-operation usage and full run cost total.
    **Called from / displayed in:** [RunHeader cost chip][header]; usage breakdown UI missing.

27) **`GET E/regressions`**
    **Purpose:** List actual regression records and failing/passing run references.
    **Called from / displayed in:** [Regressions & Alerts][regressions].

28) **`GET R/comments`**
    **Purpose:** List saved comments with author/display name and timestamp.
    **Called from / displayed in:** [DiscussionTab comment list][discussion].

29) **`POST R/comments`**
    **Purpose:** Save comment text; derive author from login.
    **Called from / displayed in:** [DiscussionTab → Post comment][discussion].

30) **`GET /api/notifications`**
    **Purpose:** List the user's notifications, with pagination/read filters.
    **Called from / displayed in:** Missing notification dropdown/list in app header.

31) **`GET /api/notifications/unread-count`**
    **Purpose:** Return unread count for the user.
    **Called from / displayed in:** Missing notification badge.

32) **`PATCH /api/notifications/<notification_id>`**
    **Purpose:** Mark the user's notification read.
    **Called from / displayed in:** Missing notification item action.

33) **`GET R/events`**
    **Purpose:** Stream ordered live run/step/action/screenshot/analysis/completion updates.
    **Called from / displayed in:** [useLiveRunEvents][live] → [StreamStatusBar][stream] and run detail refreshes.

34) **`GET /api/events`**
    **Purpose:** Stream user notifications and run/dashboard/cost update signals.
    **Called from / displayed in:** Missing application-level subscription in [AppShell][shell].

35) **`POST /internal/v1/runs/<run_id>/execution-events`**
    **Purpose:** Receive worker results; deduplicate and persist before publishing updates.
    **Called from / displayed in:** Worker → BE; FE sees results through run APIs/events.

36) **`POST /internal/v1/runs/<run_id>/ai-usage`**
    **Purpose:** Receive and save AI operation usage/cost without double-counting retries.
    **Called from / displayed in:** AI service → BE; FE reads costs through public APIs.

37) **`POST /internal/v1/runs/<run_id>/ai-cost-finalizations`**
    **Purpose:** Confirm all expected usage arrived before marking cost final.
    **Called from / displayed in:** AI service → BE; refresh displayed cost state.


## Minimum data contracts

1) **Environment**
    `id`, `project_id`, `name`, `kind`, `base_url`, optional `note`, `credential_ref`, applicable `execution_policy`. Multiple environments can share a kind.

2) **Run summary**
    `id`, persisted `run_number`, project/environment identity, flow ID/name/revision, status, branch/SHA, trigger, created/started/finished times, duration, action count, AI cost/state, execution mode, optional PR/failure references.

3) **Run detail**
    Summary + saved configuration, source run for reruns, actual last-passing/first-failing references and last event ID. Keep executed results separate from configured steps.

4) **AI usage**
    Unique usage/event IDs, run ID, revision, provider/model/operation, tokens if available, amount/currency, timestamps and estimated/final state.

5) **Notification**
    ID, recipient, run ID/number, project/environment identity, type, title/message, created time and read state.

6) **Comment**
    ID, run ID, text, author ID/display name and created time.

Lists return `{"items": [], "next_cursor": null}`. Default page size 50, max 100; run history defaults to 5. `GET E/runs` supports flow/status/date filters and orders by `created_at DESC, id DESC`. Logs use separate bounded pages; do not embed large logs/images in run lists.

Start body: `environment_id`, `flow_id`, optional `flow_revision_id`, `execution_mode`, `branch`, `commit_sha`, `pull_request`. Return **202** with `id`, `run_number`, `status: "queued"`, detail URL and events URL after the run and dispatch task are saved.

Rerun body: `{}` uses the original saved configuration; `{"configuration_source":"latest_flow"}` explicitly chooses current configuration. Return a new run, retaining the source link. Recheck current access, safety policy and credentials.

Comment body: `{"text":"..."}` → **201** saved comment. Notification PATCH: `{"read":true}` → **200** updated notification. Environment creation → **201** saved environment. Other successful reads → **200**.


## Shared implementation rules

1) **Access**
    FE sends its Supabase bearer token. BE validates it and checks user → project → environment → run ownership, including every child/file. Internal callbacks use separate job-scoped service credentials.

2) **Persistence**
    use Project → Environment → Run → run details foreign keys. Flows belong to projects; runs keep a frozen flow revision/configuration. No database/models/migrations exist yet; PostgreSQL + SQLAlchemy/Alembic is the proposed foundation.

3) **Numbering/retries**
    allocate run numbers in BE with a locked project counter and unique `(project_id, run_number)`. Save run + dispatch task together. Require `Idempotency-Key` for create environment/start/rerun/comment so retries return the same result.

4) **Statuses**
    queued, running, passed, passed_healed, failed, regression, agent_error, cancelled. Unavailable timestamps/duration/metadata are null. Queued action count is 0. Supporting passed_healed does not add heal APIs.

5) **Costs**
    pending is not zero. AI service must durably save usage before retrying delivery to BE. Deduplicate IDs; revisions replace estimates rather than add another charge. Costs may arrive after run completion; update old reporting periods too.

6) **Dashboard**
    use all records in the period, independently of latest five runs. Default timezone UTC; seven local calendar dates for execution trends; Monday-to-now for weekly spend. Pass rate = passed/passed_healed divided by passed/passed_healed/failed/regression. Attribute cost by operation time.

7) **Evidence**
    private storage; authorize downloads and issue five-minute URLs. Store explicit action/image links and real click coordinates. Default file/event retention 30 days; preserve older runs. Never expose secrets or fabricate baseline/PR/deployment references.

8) **Live updates**
    persist before publish; use ordered IDs, reconnect with `Last-Event-ID`, ignore duplicates, and refetch authoritative detail on completion. If replay expired, reload detail. User stream/polling refreshes background notifications and late costs.

9) **Notifications**
    persist one completion notification per recipient/run; retries cannot duplicate it. Default recipient is the initiating user while access remains active. Comments use the authenticated author.

10) **Errors**
    400/422 invalid request, 401 invalid login, 403 forbidden action, 404 missing/inaccessible record, 409 conflict, 410 expired artifact/replay, 503 dependency unavailable. Return `{"error":{"code":"...","message":"..."}}`.

## Frontend wiring checklist

1) Replace fixtures in `useRuns`, `useRunDetail`, `useFlows` and the mock live emitter with requests; keep Zod validation/mappers and scope query keys by user/project/environment.

2) Align [run.schema.ts][schema]: it currently expects numeric run numbers, flat identities, non-null costs/times and replay/agentic modes. Agree modes with the worker before wiring; the backend proposal uses standard.

3) Use stable environment IDs in [TopHeader][shell], not kinds. Add selection handlers and missing environment form fields.

4) [FlowDetailContent][flow] currently shows a hardcoded run's executed steps; switch to configured flow detail. [RunDetailContent][detail] computes last passing as runNumber - 1; use real references.

5) Replace generated screenshots/logs and fixed click coordinates with artifacts/results. Replace dashboard totals derived from a run list and fixed regression labels with BE data.

6) Add missing start-test, notification and trend UI; wire existing rerun, download and comment controls.

## Before implementation

1) Keep `app.run()` after all route declarations. Preserve original endpoints and coordinate legacy project-name → ID changes.

2) Agree the worker/AI protocol, actual flow/data source and Supabase/database/storage/credential configuration.

3) Build persistence/auth first, then execution/results, then costs/reporting/notifications and FE wiring.

New-flow creation, planning and heal APIs are outside this work.

[projects]: ../../BlindSpotFE/src/app/projects/page.tsx
[shell]: ../../BlindSpotFE/src/shared/ui/app-shell.tsx
[env]: ../../BlindSpotFE/src/features/environments/components/EnvironmentCards.tsx
[settings]: ../../BlindSpotFE/src/features/flows/components/FlowSettingsFields.tsx
[flows]: ../../BlindSpotFE/src/features/flows/components/FlowsList.tsx
[flow]: <../../BlindSpotFE/src/app/(app)/projects/[projectId]/flows/[flowId]/flow-detail-content.tsx>
[counts]: ../../BlindSpotFE/src/features/overview/OverviewCounters.tsx
[regressions]: ../../BlindSpotFE/src/features/overview/RegressionsFirst.tsx
[recent]: ../../BlindSpotFE/src/features/overview/RecentRunsTable.tsx
[runs]: <../../BlindSpotFE/src/app/(app)/projects/[projectId]/runs/runs-content.tsx>
[header]: <../../BlindSpotFE/src/app/(app)/projects/[projectId]/runs/[runId]/run-header.tsx>
[failure]: <../../BlindSpotFE/src/app/(app)/projects/[projectId]/runs/[runId]/failure-summary.tsx>
[steps]: <../../BlindSpotFE/src/app/(app)/projects/[projectId]/runs/[runId]/steps-pane.tsx>
[actions]: <../../BlindSpotFE/src/app/(app)/projects/[projectId]/runs/[runId]/action-row.tsx>
[analysis]: <../../BlindSpotFE/src/app/(app)/projects/[projectId]/runs/[runId]/ai-analysis-tab.tsx>
[evidence]: <../../BlindSpotFE/src/app/(app)/projects/[projectId]/runs/[runId]/evidence-pane.tsx>
[console]: <../../BlindSpotFE/src/app/(app)/projects/[projectId]/runs/[runId]/console-tab.tsx>
[network]: <../../BlindSpotFE/src/app/(app)/projects/[projectId]/runs/[runId]/network-tab.tsx>
[discussion]: <../../BlindSpotFE/src/app/(app)/projects/[projectId]/runs/[runId]/discussion-tab.tsx>
[live]: ../../BlindSpotFE/src/features/runs/api/use-live-run-events.ts
[stream]: <../../BlindSpotFE/src/app/(app)/projects/[projectId]/runs/[runId]/stream-status-bar.tsx>
[schema]: ../../BlindSpotFE/src/features/runs/api/run.schema.ts
[detail]: <../../BlindSpotFE/src/app/(app)/projects/[projectId]/runs/[runId]/run-detail-content.tsx>
