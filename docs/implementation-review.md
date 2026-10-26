# Infrastructure review — 2026-10-26

## Baseline and preservation
Read-only management metadata checks on project xzsdkgbbkkubmslqnubd returned no public application tables and the standard Supabase auth tables. No application rows or credentials were read. No production schema/data writes were performed.
Frontend baseline: bfe55b28d5eccee47c4efa74624508c4ef631f7d. Backend baseline: 9553d26cd9b104c9afbf2e7ae7a5c3c0951c9618. Existing auth service calls Supabase signInWithPassword/signUp/getUser directly. The original main repository has no migration defining the draft mapping tables.

Work is isolated in review branches copied from the original repositories. Quorum's competing drafts are preserved, not promoted. New frontend files add /workspace; the existing projects page gains one navigation link. Existing auth, presentation pages, backend service and discovery/regression code are preserved.

## Database
Migration 20261026000100_application.sql creates 10 public application tables and an app_private helper schema. It does not create/alter auth.users. It is a once-only versioned migration, not a replayable ad-hoc script.
Project creation, invitation creation and acceptance use transactional RPCs with fixed empty search paths and explicit execution grants. The identity is always auth.uid(), never caller-supplied ownership. Membership writes and worker results are unavailable to browser roles. Table and column grants complement RLS. Project cleanup skips child audit inserts once their parent is deleted, so FK cascades remain valid; a regression test verifies this while browser project deletion stays denied. Composite keys stop cross-project references. Audit records hold metadata rather than raw request content.

## Evidence
- Nine fresh-database integration groups passed, exercising multiple identities under authenticated NOSUPERUSER NOBYPASSRLS.
- Three real PostgREST HTTP tests passed: signed JWT -> role switch -> SQL RLS; rejected forged/expired/anonymous tokens; persisted project visible only to permitted user; invitation acceptance/replay.
- Frontend: 20 test files / 95 tests passed, including six new workspace interaction tests.
- Frontend TypeScript check passed, targeted ESLint passed cleanly, production build passed.
- Real browser flow passed: project -> application -> environment -> saved queued scan, reload persistence, signed-out guard and no page errors. Synthetic identity lookup was used; Data API requests reached real local PostgREST/PostgreSQL. Hosted Supabase login remains untested by these synthetic identities.

## Rollout
Review SQL, application delta and test evidence. Recheck the hosted public schema for changes made since inspection. Apply this single migration transactionally using the team's established Supabase migration workflow and record it in migration history. Do not run any rejected scratch migrations. Build/deploy the reviewed frontend using the team's existing public Supabase URL/publishable key. No management token belongs in the frontend.
After rollout, sign in through the existing auth flow, create a project/application/environment, save a scan request, reload, and verify with a separate invited user and unrelated account. Coordinate actual scan worker storage/status updates with Stevie/Sri using the defined tables or a reviewed adapter.

## Rollback
Before real application data exists, a reviewed reverse migration can remove only the new application objects. After usage begins, export application data and use a forward repair; do not drop tables as routine rollback. Revert the frontend review commit independently. Supabase-managed auth objects remain untouched.
