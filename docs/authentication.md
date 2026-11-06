# Backend-owned Supabase PKCE authentication

Ported from `feat/backend-auth` onto the `app/`-package layout
(`app/core/auth.py`, `app/core/auth_config.py`, `app/core/auth_pkce.py`,
`app/core/supabase_auth.py`, `app/services/auth.py`); the routes themselves
are declared in `main.py` alongside everything else, not a separate router.
The mechanism below is unchanged.

Shared Supabase email templates stay unchanged and must use their existing
standard `ConfirmationURL` links. This flow does not require custom email link
markup, TokenHash fragments or browser SDK code exchange. No dashboard settings,
real emails, accounts, deployments or branches are changed automatically.

## Local configuration

Use the existing project's SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY. No
service-role key is needed. Preserve existing local `.env` values; never paste
keys or callback URLs containing codes into chat.

| Backend variable | Local value / purpose |
|---|---|
| SUPABASE_URL | Existing project's HTTPS project URL |
| SUPABASE_PUBLISHABLE_KEY | Same project's publishable key |
| APP_ENV | development (production is the default) |
| AUTH_FRONTEND_ORIGINS | http://localhost:3000 |
| AUTH_BACKEND_ORIGIN | http://localhost:8000 |
| AUTH_EMAIL_FRONTEND_ORIGIN | http://localhost:3000; must be an allowed frontend origin |
| AUTH_COOKIE_SAMESITE | lax |
| AUTH_REFRESH_COOKIE_MAX_AGE | 2592000 seconds |
| AUTH_FLOW_ENCRYPTION_KEY | A persistent Fernet key, shared by all backend workers |

If exactly one frontend origin is allowed, it supplies the email frontend default.
Production origins must be explicit HTTPS origins. Local HTTP is allowed only for
localhost development. Do not mix localhost and 127.0.0.1.

Install dependencies before generating a key:

```bash
cd BlindSpotBE
make initialize
```

Generate the key ONCE into the gitignored local `.env`, without printing it.
If `.env` already contains the example placeholder for AUTH_FLOW_ENCRYPTION_KEY,
remove only that placeholder line first. This command refuses to overwrite an
existing key and preserves other settings:

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
import re
from cryptography.fernet import Fernet
p = Path('.env')
existing = p.read_text() if p.exists() else ''
if re.search(r'^\s*AUTH_FLOW_ENCRYPTION_KEY\s*=', existing, re.M):
    raise SystemExit('Existing key setting preserved; no change made.')
with p.open('a') as stream:
    stream.write('\nAUTH_FLOW_ENCRYPTION_KEY=' + Fernet.generate_key().decode() + '\n')
p.chmod(0o600)
print('Local key configured; its value was not printed.')
PY
make run
```

Do not generate a new key on each startup. Rotating/losing it invalidates pending
transactions and recovery grants. Missing/invalid encryption configuration fails
email-flow initiation closed; ordinary login/identity/logout do not require it.
Use a shared runtime secret for production replicas, configured manually.

Frontend `.env.local` needs NEXT_PUBLIC_API_BASE_URL=http://localhost:8000; retain
SDK project variables for workspace consumers. Start the frontend on localhost:3000.

## Exact Supabase redirect allowlist entries

In the EXISTING project's Authentication → URL Configuration, add these two
narrow patterns, retaining existing Site URL and other clients' entries:

```text
http://localhost:8000/auth/callback/signup/*
http://localhost:8000/auth/callback/recovery/*
```

The final segment is a random 32-character transaction identifier. Each request
uses a concrete URL under one of those paths. A single-segment wildcard is needed
to support overlapping requests without overwriting browser transactions; it is
restricted to the backend origin and callback prefix, not arbitrary destinations.
Production equivalents use your exact HTTPS backend origin and these same paths.
There is no callback `next` parameter and no user-controlled redirect destination.

Leave shared **Confirm signup** and **Reset password** templates unchanged, using
standard ConfirmationURL links. Keep existing email-confirmation/password policy.
If the project already had nonstandard templates that bypass ConfirmationURL,
compatibility must be reviewed manually; do not silently replace project-wide
markup. These instructions do not authorize dashboard changes or test emails.

## Flow, cookies and expiry

1. CSRF-protected signup/reset initiation generates an S256 challenge from a
   high-entropy verifier. Supabase receives the challenge and backend callback URL.
2. The verifier, purpose, random ID and server expiry are authenticated-encrypted
   in a per-request HttpOnly cookie. Transactions expire after 15 minutes. Up to
   eight may coexist; separate cookie names prevent lost updates across tabs.
3. The standard Supabase email link verifies the email action, then redirects to
   the backend with an authorization code. No access/refresh JWT is sent to JS.
4. The GET callback requires the corresponding browser cookie, correct purpose,
   unexpired transaction and a single code. FastAPI exchanges code+verifier at
   Supabase `/token?grant_type=pkce`. Supabase enforces code validity/single use.
5. The chosen transaction cookie is deleted on success AND failure. Success sets
   access/refresh HttpOnly cookies. All outcomes redirect with 303 to the fixed
   clean frontend `/login` (signup) or `/reset-password` (recovery), without code,
   transaction ID, provider errors or arbitrary next destinations.

The browser/device initiating the request must open the email to establish a
session. Missing, tampered, expired, wrong-purpose or reused transactions create
no session. Signup email confirmation may have already succeeded at Supabase;
the user can log in normally even when automatic exchange fails. Recovery must
be requested again from the browser that will open the email; it never falls
back to an ordinary login or SDK session as recovery proof.

Transactions use SameSite=Lax so top-level email navigation can send them even
if ordinary auth cookies use Strict. Production names are __Host-bs_pkce_<id>
(Secure, Path=/, no Domain); development uses bs_pkce_<id>. Session cookies retain
existing Secure/HttpOnly/SameSite/expiry rules. Logout and completed password
updates cancel pending transactions as well as clearing session/recovery cookies.
Standard email links retain their existing scanner/prefetch consumption risk;
PKCE protects the exchange but does not stop a scanner consuming the email link.

## Recovery permission and password updates

Only a successfully exchanged **recovery** transaction issues the encrypted
bs_recovery cookie (__Host-bs_recovery in production). It is bound to the verified
user and hashes of that session's access/refresh credentials and expires after
at most 10 minutes (also capped by the access-token lifetime).

GET `/auth/recovery` verifies identity through Supabase and validates this grant.
The reset form uses it instead of ordinary `/auth/me`. POST
`/auth/password/update` requires the same server-verified recovery permission;
a normal login, signup callback, frontend flag, forged cookie or unrelated
session cannot authorize it. Missing identity returns 401, missing/expired grant
with valid identity returns 403. The grant survives legitimate refresh only when
its original session binding matches, and refresh never extends its expiry.

A successful update attempts scope=local remote logout, clears cookies and pending
transactions, and directs the UI back to login. If remote revocation fails after
the password changed, the success message says so. Old JWTs can remain usable
until expiry; this does not claim instantaneous all-device revocation. Supabase
secure-password/MFA/reauthentication policies still apply; nonce UI is not added.

## API and request security

The "Auth" tag in the OpenAPI schema contains nine operations: signup, login,
me, refresh, logout, GET `/auth/callback/{purpose}/{transaction_id}`, GET
`/auth/recovery`, POST `/auth/password/reset-request`, and POST
`/auth/password/update`. Every other route declared in `main.py` depends on
`current_user` (directly, or via `app.core.deps`'s `ProjectAccess`/
`ProjectManage`), which performs the same Supabase verification plus the
same CSRF check on mutating requests.

All browser API calls use credentials:include. Every POST still requires an
explicit allowed Origin, application/json and X-CSRF-Protection:1. There is no
readable CSRF token. The email-navigation GET callback does not require a custom
header; its separate security boundary is the encrypted browser-bound PKCE
transaction plus Supabase code verification, not a trusted query-string flag.
CORS remains credentialed with explicit origins only. Responses are no-store and
auth/callback responses use no-referrer. Reset-request messages remain generic
for existing/nonexistent accounts and provider account-related failures.

Callback query strings are stripped from ASGI scope before routing/logging;
only the selected code is retained privately for exchange. A Uvicorn access-log
filter replaces the entire callback request target, including transaction ID,
with `/auth/callback/[redacted]`. Outgoing Supabase exchange sends credentials
only in its body. Application code logs no codes/passwords/cookies/verifiers.
Operators must separately redact callback request targets at proxies, ingress,
APM and hosting log layers before production. This task changes no cloud settings.

## Manual browser tests

1. Configure local values and add only the two redirect patterns above manually.
   Keep templates unchanged. Start backend on localhost:8000 and frontend on
   localhost:3000. Do not copy/share cookie values or callback URLs from DevTools.
2. Intentionally sign up with an address you control. Expect a check-email message
   without session tokens. Open its standard confirmation email in the same
   browser. It should pass through the backend callback and land on clean /login.
   Verify /auth/me works if exchanged, or log in normally once email is confirmed.
3. Request password recovery at /forgot-password. Open the standard email in that
   same browser. It should land on clean /reset-password; GET /auth/recovery must
   succeed before the form is shown. Submit matching new passwords, then log in
   with the new password. Reload, exercise refresh and log out via the account menu.
4. Request two links before opening either: each gets its own transaction cookie.
   Try completing them in reverse order. Completing one must not erase the other;
   signup/login must never grant password-reset permission.
5. Test reused/expired links and another browser without the initiating cookie.
   Recovery must show the request-new-link path with no authorized form. Confirmed
   signup users should still be able to log in. Normal logged-in users visiting
   /reset-password without a recovery grant must not receive reset permission.
6. Check backend access logs: only the redacted callback target should appear,
   without codes or IDs. Stop the backend to check safe outage handling. No real
   emails are sent by automated tests; these manual actions intentionally do so.

## Checks and remaining scope

```bash
source .venv/bin/activate && pytest -q tests/test_auth.py
```

`tests/test_auth.py` covers login/signup/logout/refresh/CSRF/CORS/production
cookies/concurrent sessions and config validation. PKCE/recovery/password-reset
flow tests (challenge/verifier matching, transaction encryption, overlap,
expiry/purpose/tampering, code reuse, log redaction, recovery-session
binding) existed on `feat/backend-auth` as `tests/test_email_auth.py` but were
not ported in this pass — the underlying logic is unchanged, just relocated;
porting that test file is follow-up work.

Workspace still uses the Supabase browser SDK for separate identity/data access;
its packages/helpers remain. Backend session checks never fall back to that SDK.
Resource-level roles/authorization, service callbacks, database/AI integration,
CAPTCHA, MFA/reauthentication UI and deployment are outside this task.

Official references: [PKCE](https://supabase.com/docs/guides/auth/sessions/pkce-flow),
[email templates](https://supabase.com/docs/guides/auth/auth-email-templates),
[redirect patterns](https://supabase.com/docs/guides/auth/redirect-urls),
[Auth REST API](https://raw.githubusercontent.com/supabase/auth/master/openapi.yaml).
