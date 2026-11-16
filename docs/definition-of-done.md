# MohaganyXD — BlindSpot infrastructure and database

Based on the Oct 16–19 team exchange. Stevie and Sri own discovery/classification and regression. Vanshika owns authentication. This scope builds the application infrastructure around their work.

## Acceptance criteria
- Keep the existing Supabase login/signup/password recovery and identity: auth.uid() is auth.users.id. Do not replace or alter Supabase-managed auth tables.
- Provide reviewed versioned migrations for profiles, projects, project membership, applications, environments, invitations, scans, test results, notifications and audit metadata.
- Persist project/application/environment creation and scan requests. Display genuine saved records and explicit loading, empty, error and pending states.
- Let project owners/admins invite members. Only the verified matching email may accept a live invitation; acceptance cannot replace an existing role or be replayed.
- Enable RLS on every application table. Anonymous users cannot access data; members cannot elevate roles; users cannot cross tenant boundaries, forge ownership, or write execution results/audit records.
- Validate the schema from a clean database and test access under non-superuser, non-BYPASSRLS roles. Check real HTTP token verification and persistence, not just request echoes.
- Keep the team's existing frontend presentation pages and Python service intact. Add a workspace entry point and use the existing Supabase browser client.
- Supply reproducible test commands, a passing frontend build, changes suitable for review, and clear rollout/rollback instructions.
- Apply/deploy the reviewed changes only through an authorized production rollout, then verify real hosted login and persistence.

## Boundaries
Scan execution, classification, discovery, regression algorithms, and worker ingestion are team integration work. A queued scan is only a persisted request. No fabricated execution or result is shown as complete.
Invitations are in-app records; this change does not send external email. The recipient signs in with the invited verified address.
The original Python placeholder API and team fixture pages are retained; this workspace uses Supabase's authenticated Data API and transactional database RPCs. Connecting every existing fixture screen or worker endpoint is not represented as finished here.
