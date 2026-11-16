# Assigned endpoint completion

The 17 functions marked `SRINIVAS, WORK ON THESE` in `origin/main` (`9ec4c56`)
are implemented on `feat/backend-ai-integration`, including the five handlers
that previously remained 501. Every handler delegates to a service and keeps
project/session or job-token authorization. There are no remaining `todo()`
handlers in `main.py`.

| Main assignment | Implementation |
| --- | --- |
| List/create/get/update/delete requirements; approval (6) | `app/services/resources.py`: scoped CRUD, criterion reconciliation, approval invalidation and history protection |
| Create/read imports (2) | `app/services/imports.py`: retained originals, stable operation IDs, upstream extraction, linked draft requirements and warnings |
| Download source document (1) | `app/services/private_storage.py`: import/document/project chain, integrity check, five-minute grant |
| List/get/update environments (3) | `app/services/resources.py`: revisioned settings and encrypted write-only credentials |
| Verify environment (1) | `app/services/verification.py`: authenticated aiservice request, persisted verification record, revision check before setting verified_at |
| Fetch evidence (1) | `app/services/private_storage.py`: authorize the saved result citation, retrieve only from its saved executor job, verify SHA-256, cache privately and issue a grant |
| Execution/usage/cost callbacks (3) | `app/services/callbacks.py`: job/run authentication, durable replay handling, result persistence and count/digest reconciliation |

## Required companion

Use aiservice branch `feat/backend-capabilities`, built on the audited
`feat/JobIntake` implementation. Its additional service-authenticated APIs are:

* `POST /v1/imports`: normalize TXT/Markdown/PDF/DOCX documents, extract only
  documented requirements, attach server-selected source passages, and return
  typed draft candidates. The model only selects passage IDs; it cannot invent
  the stored source excerpt. Human review is still required for model content.
* `POST /v1/environments/verify`: deterministic Playwright login check. Requires
  configured username/email, password, and a success selector that becomes
  visible after submission. Already-visible or missing proof is inconclusive.
* `GET /v1/jobs/{job_id}/evidence/{evidence_id}`: read job-bound operational
  evidence over HTTP. BE never connects to aiservice's database.

The original A1 job intake and callback API remains compatible. A1's stub engine
is still a stub; the browser capability here verifies configured login forms,
not arbitrary business flows. SSO/MFA/captcha flows are not automated by this
credential-form verifier and return an unsuccessful/inconclusive result.

## Backend configuration

Apply `alembic upgrade head` and configure the existing service URL/token and
environment encryption key. New settings:

```text
PRIVATE_STORAGE_DIR=/absolute/path/on/a/persistent/private/volume
DOWNLOAD_SIGNING_KEY=<persistent dedicated Fernet key>
CAPABILITY_TIMEOUT_SECONDS=100
```

Use a persistent volume shared by every backend instance. Local ephemeral Cloud
Run disks are not suitable for retained documents/evidence. Objects have opaque
server-generated keys, directory mode 0700 when created, and file mode 0600.
Do not expose this directory through static hosting. No cloud bucket is
provisioned by this change.

`AUTH_BACKEND_ORIGIN` must be configured to build download redirects. Grants
redirect to `GET /downloads/{token}` and require the same authenticated user,
current project access, and a valid five-minute encrypted grant. Redemption
checks ownership again. Files are attachments, have nosniff/sandbox headers,
and are not exposed as executable app HTML. Download grants are redacted in
structured request logs.

POST imports as multipart fields `brd`, `srs`, and optional `design_spec`; the
whole set is limited to 10 MiB. Send a stable `Idempotency-Key` for retries.
Original files and pending import metadata are committed before extraction;
retrying the same key resumes the same operation and cannot create duplicate
requirements. A changed upload with the same key is 409. Unavailable extraction
returns 503; no fake requirements are created. GET of a pending import is 409.
Once completed, GET returns the linked current requirement records and retained
source metadata; deleting a requirement removes that link, not the original file.

Verification returns 202 with `status` verified/rejected/inconclusive/stale.
It waits for the bounded upstream check; this is not a queued browser-job API.
A stale result is retained but never changes the edited environment's
verification timestamp. Request bodies and credentials are not logged.

## aiservice configuration

```text
EXTRACTION_API_URL=https://api.openai.com/v1
EXTRACTION_API_KEY=<provider credential>
EXTRACTION_MODEL=<configured model supporting JSON-object output>
EXTRACTION_TIMEOUT_SECONDS=80
VERIFICATION_ENABLED=true
VERIFICATION_TIMEOUT_SECONDS=30
VERIFICATION_ALLOWED_PRIVATE_HOSTS=
VERIFICATION_BROWSER_EXECUTABLE=
```

Install aiservice's `.[engine]` extra and run `python -m playwright install
chromium`, or configure a compatible Chrome/Chromium executable. Private targets
are blocked by default; explicitly allow development/internal application
hostnames only when intended. Metadata/link-local endpoints are always blocked.
Browser requests are restricted to the approved origin; service workers,
WebSockets and downloads are blocked. Use deployment network controls as well
when executing against untrusted applications.

The compatible provider sends one bounded Chat Completions request, without
automatic model retries, with JSON-object output and storage disabled. The
[official API reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
describes the transport fields. No default paid model is selected. Missing
configuration returns 503. Tests inject a fake model transport; no real provider
request was made during verification.

Capability operation IDs and result caches persist in aiservice's own DB.
Extraction records a reservation before the provider call, then measured tokens
when reported. Price is unknown, so amount remains null. A failed/interrupted
operation is not automatically repeated: a provider may already have billed it.
Inspect `capability_operations` and `capability_usage`; after confirming the
external outcome, an operator can resolve the cached state or deliberately
start a new import. Do not delete reservations and blindly replay paid calls.

## Validation

The test suites cover PostgreSQL migration round trips/schema drift, every
previously incomplete handler, import replay/failure, private downloads and
revocation/expiry, evidence integrity/cache behavior, revision races, exact
cross-service schemas, and real Chromium success/failure against a synthetic
local login form. The cross-service test runs the actual aiservice HTTP API,
with a fake model transport and real Chromium, through the backend's handlers.
The real A1 job round trip additionally fetches its cited evidence over HTTP
and redeems the backend download grant.

Run with disposable PostgreSQL databases only:

```sh
# Backend
AISERVICE_REPO=/absolute/path/to/aiservice-capabilities \
RUN_BROWSER_CAPABILITY_TEST=1 \
BLINDSPOT_TEST_DATABASE_URL="$DATABASE_URL" .venv/bin/python -m pytest -q

# aiservice (different DATABASE_URL from BE)
AISERVICE_TEST_POSTGRES=1 BLINDSPOT_BE_REPO=/absolute/path/to/backend-integration \
RUN_BROWSER_CAPABILITY_TEST=1 .venv/bin/python -m pytest -q
```

No production database, external application login, real model request, or cloud
resource was used. Remote cancellation and full browser business-flow engines
remain separate work; none of the 17 assigned handlers depends on those APIs.

Recorded verification: **93 backend tests and 25 subtests passed**, with 15
optional external-infrastructure checks skipped; **119 aiservice tests passed**
with PostgreSQL and real-browser opt-ins enabled. Migration round trips and
model/schema drift checks passed in both suites.
