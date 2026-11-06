# Backend endpoint security inventory

All 33 user-facing feature operations now require a backend-managed Supabase
session verified by the existing `current_user` dependency (GET Supabase `/user`).
Missing/invalid access sessions return 401; provider outages return 503. Cookie
presence, Authorization/user-ID headers, JSON user IDs, frontend roles and decoded
unverified JWT claims do not authenticate a request.

## Public and authentication routes

| Operation | Protection |
|---|---|
| GET /, HEAD / | Public health only |
| GET/HEAD /docs, /redoc, /docs/oauth2-redirect, /openapi.json | Public framework metadata |
| OPTIONS/preflight | Public method/CORS metadata; no handler/resource access |
| POST /auth/signup | Existing Origin + JSON + X-CSRF-Protection:1 policy; no prior session required |
| POST /auth/login | Same entry-point CSRF policy; Supabase verifies credentials |
| POST /auth/password/reset-request | Same CSRF policy; generic response, browser-bound PKCE transaction |
| GET /auth/callback/{purpose}/{transaction_id} | Encrypted browser-bound, purpose/expiry-checked PKCE state plus Supabase code exchange; not ordinary feature auth |
| GET /auth/me | Supabase-verified access session |
| GET /auth/recovery | Verified access session plus server-issued recovery grant bound to user/session |
| POST /auth/password/update | Verified recovery grant/session plus existing CSRF policy |
| POST /auth/refresh | Existing CSRF policy and Supabase refresh-token validation/rotation; access may be expired |
| POST /auth/logout | Existing CSRF policy; current-session revocation/cookie cleanup; idempotent if no session |

These policies stay separate. No global user dependency is added to signup,
login, recovery initiation or PKCE callbacks. Recovery cannot fall back to a
normal login or legacy SDK session. PKCE logging redaction remains unchanged.

## User-facing feature operations

Every operation below uses `FEATURE_SECURITY`/`feature_user`. Every listed GET
also has a protected generated HEAD operation, excluded from OpenAPI. POST/PATCH
operations require the exact auth mutation protocol **after** session verification:
allowed Origin, Content-Type:application/json and X-CSRF-Protection:1. Even a
bodyless feature action such as artifact download must send JSON `{}`. There is
no readable CSRF token. Browser requests use credentials:include. CORS does not
replace server-side CSRF checks.

| Method | Path | Existing handler status after successful security checks |
|---|---|---|
| POST | `/create-project` | 201 |
| POST | `/dashboard` | 200 |
| POST | `/accounts` | 200 |
| POST | `/environments` | 200 |
| POST | `/projects/{project_name}` | 200 |
| POST | `/projects/{project_name}/flows/{flow_id}` | 200 |
| POST | `/projects/{project_name}/run-test` | 200 |
| GET | `/projects` | 501 |
| GET | `/environments` | 501 |
| GET | `/environments/{environment_id}` | 501 |
| GET | `/projects/{project_id}/credential-references` | 501 |
| GET | `/projects/{project_id}/execution-policies` | 501 |
| GET | `/projects/{project_id}/flows` | 501 |
| GET | `/projects/{project_id}/flows/{flow_id}` | 501 |
| GET | `/dashboard` | 501 |
| GET | `/projects/{project_id}/environments/{environment_id}/runs` | 501 |
| GET | `/projects/{project_id}/environments/{environment_id}/runs/{run_id}` | 501 |
| POST | `/projects/{project_id}/environments/{environment_id}/runs/{run_id}/reruns` | 501 |
| GET | `/projects/{project_id}/environments/{environment_id}/runs/{run_id}/steps` | 501 |
| GET | `/projects/{project_id}/environments/{environment_id}/runs/{run_id}/steps/{step_id}/actions` | 501 |
| GET | `/projects/{project_id}/environments/{environment_id}/runs/{run_id}/failures` | 501 |
| GET | `/projects/{project_id}/environments/{environment_id}/runs/{run_id}/artifacts` | 501 |
| POST | `/projects/{project_id}/environments/{environment_id}/runs/{run_id}/artifacts/{artifact_id}/download` | 501 |
| GET | `/projects/{project_id}/environments/{environment_id}/runs/{run_id}/logs` | 501 |
| GET | `/projects/{project_id}/environments/{environment_id}/runs/{run_id}/ai-usage` | 501 |
| GET | `/projects/{project_id}/environments/{environment_id}/regressions` | 501 |
| GET | `/projects/{project_id}/environments/{environment_id}/runs/{run_id}/comments` | 501 |
| POST | `/projects/{project_id}/environments/{environment_id}/runs/{run_id}/comments` | 501 |
| GET | `/notifications` | 501 |
| GET | `/notifications/unread-count` | 501 |
| PATCH | `/notifications/{notification_id}` | 501 |
| GET | `/projects/{project_id}/environments/{environment_id}/runs/{run_id}/events` | 501 |
| GET | `/events` | 501 |

The existing response bodies/statuses, paths, methods, Swagger groups and four
legacy deprecations are preserved for requests that pass the new boundary. The
200/201 legacy handlers only echo input or return static test status: they do not
create projects/environments, run tests, authorize a project or call services.
All existing 501 operations remain unimplemented. No real project/resource data
is loaded, modified, signed or streamed by these handlers.

Verified identity is available server-side as `request.state.current_user` (a
validated User containing only id/email), or by injecting `Depends(feature_user)`.
Future ownership/author/recipient logic must use that verified id, never the
client's data_received fields. Current echo responses may contain client-supplied
user_id/role values as arbitrary input; those are not the authenticated identity
and are not used for permissions. Authentication alone is NOT project access.

## Internal service callbacks: still nonfunctional

| Method | Path | Status |
|---|---|---|
| POST | /internal/v1/runs/{run_id}/execution-events | 501 |
| POST | /internal/v1/runs/{run_id}/ai-usage | 501 |
| POST | /internal/v1/runs/{run_id}/ai-cost-finalizations | 501 |

These have no ordinary-user dependency or cookie/CSRF authentication substitute.
Anonymous callers and logged-in users both reach only the existing fixed 501
response. Payloads are not processed/persisted and service integration is not
implemented. They need a separately designed trusted service identity, job/run
binding, replay/deduplication policy and signature/token validation before use.
No service key or role model was invented by this task.

## Authorization evidence and decisions still missing

Inspected backend source/docs and frontend workspace source. No checked-in SQL
schema/migrations, RLS definitions, backend membership models, or trusted
project-access service was found in either repository. Backend semantic/schemas.py
contains no authoritative database schema. Frontend use-workspace.ts references
projects.id/name/owner_id and invitations.role; workspace.ts calls create_project,
invite_member and accept_invitation RPCs. Those TypeScript fields/call sites do
not define who may access a project, and RPC/policy implementations are absent.
Do not infer owner-only permissions, admin/member powers, membership tables or
RLS guarantees from them. user_metadata is user-editable and grants no authority.

Before activating any real feature operation, provide/verify:

- The authoritative project membership/ownership relation and allowed actions.
- Stable project identity and the mapping of legacy project_name routes to IDs.
- Foreign-key/ownership chains for environment, flow, run, step, action and artifact.
- Notification recipient rules and comment author/run-access rules.
- Actual RLS/RPC/policy definitions, role provenance if applicable, and backend
  querying strategy under the verified user identity.

Until then, all feature resources remain placeholders and no project permission
is approved. There is no implemented feature cross-project authorization policy
to test or claim as enforced. Available identity-bound authorization (the recovery
grant) rejects mismatched users/sessions in existing tests. User A/B tests also
prove request/body/query roles cannot replace the verified feature identity.

## Security gaps addressed and remaining

Previously CSRF checks covered auth POSTs but no feature mutations. Feature
routes also lacked verified-session checks and private response-cache controls.
The generated HEAD registration copied endpoint/status but not dependencies;
it now explicitly copies route.dependencies to avoid an authentication bypass.
Authenticated feature responses are no-store/no-referrer, including HEAD.
AuthError responses already use no-store; health and framework metadata remain
public. OPTIONS/CORS preflight never executes a resource handler.

Remaining: resource authorization/schema decisions, separate service auth,
actual feature implementations, rate/abuse controls, workspace SDK/data migration
and external callback-log redaction. Existing access JWTs may remain valid until
expiry after logout; do not claim immediate JWT revocation. Every feature request
performs live Supabase verification, so auth-service outages return 503.

## Verification

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Tests mock only Supabase HTTP responses, not current_user. They cover every
protected operation for anonymous/invalid/valid users, all feature mutations'
CSRF/content-type checks, generated HEAD protection, client identity spoofing,
verification outages, public health/docs/auth entry points, unchanged internal
501 responses, existing PKCE/recovery flows and route contracts. No real accounts,
project queries, emails, cloud changes or frontend edits are performed.
