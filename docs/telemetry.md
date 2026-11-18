# Sentry telemetry

The API uses the official FastAPI/Starlette, HTTPX and SQLAlchemy integrations.
It continues incoming `sentry-trace`/`baggage` context. CORS permits these headers
only for the existing configured frontend origins; authentication/CSRF is unchanged.

`X-Request-ID` remains a UUID, echoed in responses/errors, included in structured
stdout logs and Sentry event tags, and forwarded to Supabase Auth/PostgREST.
It is **not** a trace ID or an authorization credential. Sentry generates the
trace/span IDs. Completion logs include both IDs when a trace is active.

The local ignored `.env` is configured; `.env.sentry` holds a separate copy for controlled verification.

## Configuration

- `SENTRY_DSN`: blank disables Sentry initialization/export.
- `SENTRY_ENVIRONMENT`: explicitly set `staging` or `production` in deployments.
- `SENTRY_RELEASE`: immutable deployment commit or release identifier.
- `SENTRY_TRACES_SAMPLE_RATE`: fraction between 0 and 1; default 0.1. Preserve
  the upstream sampling decision so frontend/backend stay connected.
- `SENTRY_TRACE_PROPAGATION_TARGETS`: JSON array of **anchored** regexes matching
  trusted downstream origins. Default `[]` sends no trace headers downstream.
  Example: `["^https://your-project\\.supabase\\.co/"]`.

Load the ignored `.env.sentry` into the process environment locally; existing
application credentials/configuration are left intact. Do not commit that file.
The new Sentry organization is `blindspot-capstone`; API project `blindspot-backend`.

## Privacy and costs

No replay, profiling, user info, cookies, headers, HTTP bodies, query parameters,
exception values, local variables, breadcrumbs or SQL statements are exported.
Events preserve exception types and stack locations. Span descriptions are
reduced to operation metadata. Stdout completion routes use route templates,
never callback/download credentials. Existing exception responses stay sanitized.
Only fixed completion messages for sampled requests enter Sentry Logs; arbitrary
third-party log messages are not forwarded. Normal stdout logging is unchanged.

SDK instrumentation shows our outbound HTTP timings and our SQLAlchemy queries.
It cannot expose Supabase's internal PostgREST/PostgreSQL spans unless those
services are separately instrumented. Do not promise that visibility.

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
