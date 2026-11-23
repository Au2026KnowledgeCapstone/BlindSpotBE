# Sentry telemetry

The API uses the official FastAPI/Starlette, HTTPX and SQLAlchemy integrations.
It continues incoming `sentry-trace`/`baggage` context. CORS permits these headers
only for the existing configured frontend origins; authentication/CSRF is unchanged.

`X-Request-ID` remains a UUID, echoed in responses/errors, included in structured
stdout logs and Sentry event tags, and forwarded to Supabase Auth/PostgREST.
It is **not** a trace ID or an authorization credential. Sentry generates the
trace/span IDs. Completion logs include both IDs only when the trace is actually
sampled — an unsampled request's ids are minted locally and never reach Sentry,
so exporting them would point at traces that do not exist.

## Configuration

- `SENTRY_DSN`: blank disables Sentry initialization/export. A DSN alone is not
  sufficient: `configure_telemetry()` also no-ops when it detects pytest, so a
  CI runner that defines `SENTRY_DSN` cannot ship test traffic into the real
  project (importing `main` is what enables telemetry, and the suite imports
  `main`). Tests that drive the SDK pass `allow_in_tests=True` with a localhost
  DSN and an in-memory transport. Note this guard cannot key off `APP_ENV`:
  that variable is a closed enum and `AuthSettings.from_env()` rejects any
  value other than `development`/`production`.
- `SENTRY_ENVIRONMENT`: explicitly set `staging` or `production` in deployments.
- `SENTRY_RELEASE`: immutable deployment commit or release identifier.
- `SENTRY_TRACES_SAMPLE_RATE`: fraction between 0 and 1; default 0.1. Preserve
  the upstream sampling decision so frontend/backend stay connected.
- `SENTRY_TRACE_PROPAGATION_TARGETS`: JSON array of **anchored** regexes matching
  trusted downstream origins. Default `[]` sends no trace headers downstream.
  Example: `["^https://your-project\\.supabase\\.co/"]`. A bare or
  comma-separated regex is also accepted, and entries that do not compile are
  dropped — the SDK matches these with an unguarded `re.search` on every
  outbound request, and no optional telemetry setting may fail the service.

Keep Sentry settings in the ignored `.env` alongside existing application
configuration; a blank value for any of them means "use the default". The Sentry
organization is `blindspot-capstone`; API project `blindspot-backend`.

## Privacy and costs

No replay, profiling, user info, cookies, headers, HTTP bodies, query parameters,
exception values, local variables, source context, breadcrumbs or SQL statements
are exported. Two layers enforce this: `data_collection` stops the SDK gathering
these in the first place, and the `before_send*` scrubbers allowlist what may
leave. Both matter — note that a bare `False` is *not* an opt-out for
`cookies`/`http_headers`/`url_query_params` (the SDK falls back to its default
denylist mode and keeps collecting), and `include_local_variables` is ignored
once `data_collection` is set, so frame opt-outs must be repeated there.

Events preserve exception types and stack locations. Span descriptions are
reduced to operation metadata. Paths are reduced by `safe_path`, which keeps
route templates intact — so distinct endpoints stay distinct in Sentry — while
masking concrete UUIDs, numeric ids and opaque tokens, and redacting everything
after a `callback`/`downloads` segment. Existing exception responses stay sanitized.
Only fixed completion messages for sampled requests enter Sentry Logs; arbitrary
third-party log messages are not forwarded. Normal stdout logging is unchanged.

SDK instrumentation shows our outbound HTTP timings and our SQLAlchemy queries.
It cannot expose Supabase's internal PostgREST/PostgreSQL spans unless those
services are separately instrumented. Do not promise that visibility.

The noisy/PII-prone default integrations (logging, modules, argv, stdlib,
threading) are off, but `atexit`, `excepthook` and `dedupe` are kept on purpose:
the span and log batchers buffer for ~5s, so without the atexit hook a SIGTERM
(deploy, scale-down, restart) silently drops the telemetry that explains the
shutdown, and without excepthook a fatal uncaught exception is never reported.

## Validation and rollout

`tests/test_telemetry.py` uses an in-memory transport, an instrumented ASGI app,
and mocked outbound HTTP; it verifies a browser-format incoming trace continues
through HTTPX, request IDs persist, and sensitive values are removed. No live
Supabase/database credentials are required.

Deploy code/config through the team's normal review process, with the matching
frontend tracing changes. Verify a synthetic staging signup failure, find the
request ID in logs, open its trace, and confirm the browser/API share a trace ID.
Use rate 1 only for controlled verification, then restore 0.1 (or the agreed rate).
No permanent public crash endpoint is added. Disable via blank DSN/restart.

Official references:
- https://docs.sentry.io/platforms/python/integrations/fastapi/
- https://docs.sentry.io/concepts/key-terms/tracing/distributed-tracing/
