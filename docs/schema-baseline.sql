-- =============================================================================
-- BlindSpot — Supabase `public` schema baseline
--
-- Reconstructed from the live project (ref xzsdkgbbkkubmslqnubd) on 2026-11-05
-- by reading the system catalogs. It captures the state created by Supabase
-- migration `20261026231753_application_infrastructure`.
--
-- WHY THIS FILE EXISTS
--   Until now this schema existed ONLY in the live database. No SQL for the
--   RLS policies, the SECURITY DEFINER RPCs, the audit triggers or the
--   RLS auto-enable event trigger was in any repository. A single mistaken
--   DDL statement would have destroyed work that could not be recovered from
--   source control.
--
-- WHAT IT IS AND IS NOT
--   This is a reference baseline, not a verified `pg_dump`. It was assembled
--   from pg_catalog queries, so object ORDER here is hand-arranged for
--   dependency correctness but has not been executed against an empty
--   database. Before trusting it for recovery, replay it into a scratch
--   Postgres and diff the result.
--
--   It deliberately does NOT include: Supabase-managed schemas (auth, storage,
--   realtime), role definitions, or grants Supabase sets up itself.
--
-- RELATIONSHIP TO ALEMBIC
--   BlindSpotBE's Alembic owns the `blindspot` schema only. This file
--   documents `public`, which stays under Supabase's own migration history.
--   Do not fold it into an Alembic revision.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Helper schema. Not exposed through PostgREST; `authenticated` has USAGE so
-- the RLS policies below can call these.
-- -----------------------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS app_private;

-- Owner, or any member of the project.
CREATE OR REPLACE FUNCTION app_private.can_access(p uuid)
 RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO ''
AS $function$
  SELECT auth.uid() IS NOT NULL AND (
    EXISTS(SELECT 1 FROM public.projects WHERE id=p AND owner_id=auth.uid()) OR
    EXISTS(SELECT 1 FROM public.project_members WHERE project_id=p AND user_id=auth.uid()))
$function$;

-- Owner, or a member whose role is 'admin'. Note: does NOT accept role='owner'
-- from project_members — ownership is read from projects.owner_id.
CREATE OR REPLACE FUNCTION app_private.can_manage(p uuid)
 RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO ''
AS $function$
  SELECT auth.uid() IS NOT NULL AND (
    EXISTS(SELECT 1 FROM public.projects WHERE id=p AND owner_id=auth.uid()) OR
    EXISTS(SELECT 1 FROM public.project_members WHERE project_id=p AND user_id=auth.uid() AND role='admin'))
$function$;

-- Only returns an address once the user has confirmed it.
CREATE OR REPLACE FUNCTION app_private.verified_email()
 RETURNS text LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO ''
AS $function$
  SELECT lower(email) FROM auth.users WHERE id=auth.uid() AND email_confirmed_at IS NOT NULL
$function$;

-- -----------------------------------------------------------------------------
-- Tables
-- -----------------------------------------------------------------------------

CREATE TABLE public.profiles (
  user_id      uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  display_name text NOT NULL DEFAULT ''::text CHECK (length(display_name) <= 100),
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.projects (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id    uuid NOT NULL REFERENCES auth.users(id),
  name        text NOT NULL CHECK (length(btrim(name)) >= 1 AND length(btrim(name)) <= 120),
  description text NOT NULL DEFAULT ''::text CHECK (length(description) <= 2000),
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.project_members (
  project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
  user_id    uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  role       text NOT NULL CHECK (role = ANY (ARRAY['owner','admin','member'])),
  PRIMARY KEY (project_id, user_id)
);

-- The (project_id, id) unique keys below exist so every child FK can carry
-- project_id down the chain. That makes it structurally impossible to attach a
-- row to a parent in a different project. Worth preserving in any redesign.
CREATE TABLE public.applications (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
  name       text NOT NULL CHECK (length(btrim(name)) >= 1 AND length(btrim(name)) <= 120),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, id)
);

CREATE TABLE public.environments (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id           uuid NOT NULL,
  application_id       uuid NOT NULL,
  name                 text NOT NULL CHECK (length(btrim(name)) >= 1 AND length(btrim(name)) <= 120),
  kind                 text NOT NULL CHECK (kind = ANY (ARRAY['development','staging','production'])),
  base_url             text NOT NULL CHECK (base_url ~ '^https?://[^[:space:]]+$' AND length(base_url) <= 2048),
  credential_reference text CHECK (length(credential_reference) <= 200),
  created_at           timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (project_id, application_id)
    REFERENCES public.applications(project_id, id) ON DELETE CASCADE,
  UNIQUE (project_id, id)
);

CREATE TABLE public.scans (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id     uuid NOT NULL,
  environment_id uuid NOT NULL,
  requested_by   uuid NOT NULL DEFAULT auth.uid() REFERENCES auth.users(id),
  status         text NOT NULL DEFAULT 'queued'
                   CHECK (status = ANY (ARRAY['queued','running','passed','failed','cancelled'])),
  created_at     timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (project_id, environment_id)
    REFERENCES public.environments(project_id, id) ON DELETE CASCADE,
  UNIQUE (project_id, id)
);

CREATE TABLE public.test_results (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL,
  scan_id    uuid NOT NULL,
  name       text NOT NULL CHECK (length(btrim(name)) >= 1 AND length(btrim(name)) <= 200),
  status     text NOT NULL CHECK (status = ANY (ARRAY['passed','failed','skipped'])),
  summary    text NOT NULL DEFAULT ''::text CHECK (length(summary) <= 10000),
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (project_id, scan_id)
    REFERENCES public.scans(project_id, id) ON DELETE CASCADE
);

CREATE TABLE public.invitations (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id  uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
  email       text NOT NULL CHECK (email = lower(btrim(email))
                 AND email ~ '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$'),
  role        text NOT NULL CHECK (role = ANY (ARRAY['admin','member'])),
  invited_by  uuid NOT NULL REFERENCES auth.users(id),
  expires_at  timestamptz NOT NULL DEFAULT (now() + interval '7 days'),
  accepted_by uuid REFERENCES auth.users(id),
  accepted_at timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now(),
  -- accepted_by and accepted_at are set together or not at all.
  CHECK ((accepted_by IS NULL) = (accepted_at IS NULL))
);

CREATE TABLE public.notifications (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  project_id uuid REFERENCES public.projects(id) ON DELETE CASCADE,
  message    text NOT NULL CHECK (length(message) <= 1000),
  read_at    timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.audit_logs (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
  actor_id   uuid REFERENCES auth.users(id) ON DELETE SET NULL,
  entity     text NOT NULL,
  entity_id  uuid NOT NULL,
  action     text NOT NULL CHECK (action = ANY (ARRAY['INSERT','UPDATE','DELETE'])),
  created_at timestamptz NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- Indexes beyond the implicit primary/unique ones
-- -----------------------------------------------------------------------------

-- Leads with user_id so "which projects am I in" uses an index. The primary key
-- leads with project_id and cannot serve that query.
CREATE INDEX project_members_user ON public.project_members (user_id, project_id);

CREATE INDEX invitations_email ON public.invitations (email);

-- One pending invitation per (project, email); accepted rows are exempt, so an
-- expired invite can be renewed while history is preserved.
CREATE UNIQUE INDEX invitations_pending_email
  ON public.invitations (project_id, email) WHERE accepted_at IS NULL;

CREATE INDEX notifications_user ON public.notifications (user_id, created_at DESC);

-- NOTE: projects.owner_id has no index. can_access() scans projects for the
-- owner half of its check on every RLS-filtered query. Cheap to add.

-- -----------------------------------------------------------------------------
-- Row level security
--
-- Read the gaps as carefully as the policies. There is no INSERT policy on
-- test_results, no UPDATE policy on scans, and no DELETE policy anywhere. The
-- schema assumes a trusted writer for results and status transitions — which is
-- exactly the seam BlindSpotBE fills.
-- -----------------------------------------------------------------------------

ALTER TABLE public.profiles         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.projects         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.project_members  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.applications     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.environments     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.scans            ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.test_results     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invitations      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notifications    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_logs       ENABLE ROW LEVEL SECURITY;

CREATE POLICY profile_self ON public.profiles FOR ALL TO authenticated
  USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

CREATE POLICY project_read ON public.projects FOR SELECT TO authenticated
  USING (app_private.can_access(id));
CREATE POLICY project_update ON public.projects FOR UPDATE TO authenticated
  USING (app_private.can_manage(id)) WITH CHECK (app_private.can_manage(id));

CREATE POLICY member_read ON public.project_members FOR SELECT TO authenticated
  USING (app_private.can_access(project_id));

CREATE POLICY application_read ON public.applications FOR SELECT TO authenticated
  USING (app_private.can_access(project_id));
CREATE POLICY application_insert ON public.applications FOR INSERT TO authenticated
  WITH CHECK (app_private.can_manage(project_id));
CREATE POLICY application_update ON public.applications FOR UPDATE TO authenticated
  USING (app_private.can_manage(project_id)) WITH CHECK (app_private.can_manage(project_id));

CREATE POLICY environment_read ON public.environments FOR SELECT TO authenticated
  USING (app_private.can_access(project_id));
CREATE POLICY environment_insert ON public.environments FOR INSERT TO authenticated
  WITH CHECK (app_private.can_manage(project_id));
CREATE POLICY environment_update ON public.environments FOR UPDATE TO authenticated
  USING (app_private.can_manage(project_id)) WITH CHECK (app_private.can_manage(project_id));

CREATE POLICY scan_read ON public.scans FOR SELECT TO authenticated
  USING (app_private.can_access(project_id));
-- A client may queue work, but cannot set its status or attribute it to someone else.
CREATE POLICY scan_insert ON public.scans FOR INSERT TO authenticated
  WITH CHECK (app_private.can_access(project_id)
              AND requested_by = auth.uid()
              AND status = 'queued');

CREATE POLICY result_read ON public.test_results FOR SELECT TO authenticated
  USING (app_private.can_access(project_id));

CREATE POLICY invitation_read ON public.invitations FOR SELECT TO authenticated
  USING (app_private.can_manage(project_id) OR email = app_private.verified_email());

CREATE POLICY notification_self ON public.notifications FOR SELECT TO authenticated
  USING (user_id = auth.uid());
CREATE POLICY notification_read_state ON public.notifications FOR UPDATE TO authenticated
  USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

CREATE POLICY audit_read ON public.audit_logs FOR SELECT TO authenticated
  USING (app_private.can_manage(project_id));

-- -----------------------------------------------------------------------------
-- RPCs. All SECURITY DEFINER with an empty search_path.
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.create_project(p_name text, p_description text DEFAULT ''::text)
 RETURNS public.projects LANGUAGE plpgsql SECURITY DEFINER SET search_path TO ''
AS $function$
DECLARE result public.projects;
BEGIN
 IF auth.uid() IS NULL THEN RAISE EXCEPTION 'Authentication required' USING ERRCODE='42501'; END IF;
 INSERT INTO public.projects(owner_id,name,description) VALUES(auth.uid(),btrim(p_name),p_description) RETURNING * INTO result;
 INSERT INTO public.project_members(project_id,user_id,role) VALUES(result.id,auth.uid(),'owner');
 RETURN result;
END $function$;

CREATE OR REPLACE FUNCTION public.invite_member(p_project_id uuid, p_email text, p_role text DEFAULT 'member'::text)
 RETURNS public.invitations LANGUAGE plpgsql SECURITY DEFINER SET search_path TO ''
AS $function$
DECLARE result public.invitations;
BEGIN
 IF NOT app_private.can_manage(p_project_id) THEN RAISE EXCEPTION 'Not authorized' USING ERRCODE='42501'; END IF;
 -- Expired pending invitations may be renewed; accepted records remain immutable.
 INSERT INTO public.invitations(project_id,email,role,invited_by)
 VALUES(p_project_id,lower(btrim(p_email)),p_role,auth.uid())
 ON CONFLICT(project_id,email) WHERE accepted_at IS NULL
 DO UPDATE SET role=excluded.role,invited_by=excluded.invited_by,expires_at=now()+interval '7 days'
 RETURNING * INTO result;
 RETURN result;
END $function$;

CREATE OR REPLACE FUNCTION public.accept_invitation(p_invitation_id uuid)
 RETURNS public.project_members LANGUAGE plpgsql SECURITY DEFINER SET search_path TO ''
AS $function$
DECLARE invitation public.invitations; result public.project_members;
BEGIN
 IF auth.uid() IS NULL THEN RAISE EXCEPTION 'Authentication required' USING ERRCODE='42501'; END IF;
 SELECT * INTO invitation FROM public.invitations WHERE id=p_invitation_id FOR UPDATE;
 IF invitation.id IS NULL OR invitation.email IS DISTINCT FROM app_private.verified_email()
 OR invitation.expires_at<=now() OR invitation.accepted_at IS NOT NULL THEN
  RAISE EXCEPTION 'Invitation unavailable' USING ERRCODE='42501';
 END IF;
 -- Existing member roles are never replaced by accepting an invitation.
 INSERT INTO public.project_members(project_id,user_id,role)
 VALUES(invitation.project_id,auth.uid(),invitation.role)
 ON CONFLICT(project_id,user_id) DO NOTHING;
 UPDATE public.invitations SET accepted_by=auth.uid(),accepted_at=now() WHERE id=invitation.id;
 SELECT * INTO result FROM public.project_members WHERE project_id=invitation.project_id AND user_id=auth.uid();
 INSERT INTO public.notifications(user_id,project_id,message) VALUES(auth.uid(),invitation.project_id,'You joined the project.');
 RETURN result;
END $function$;

-- -----------------------------------------------------------------------------
-- Audit triggers
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION app_private.audit_change()
 RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path TO ''
AS $function$
DECLARE row_data jsonb; project uuid; entity_id uuid;
BEGIN
 row_data=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
 project=CASE WHEN TG_TABLE_NAME='projects' THEN (row_data->>'id')::uuid ELSE (row_data->>'project_id')::uuid END;
 -- Cascading project deletion also deletes its audit history. Do not create
 -- child audit rows referencing a parent already removed by that statement.
 IF NOT EXISTS(SELECT 1 FROM public.projects WHERE id=project) THEN
  RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
 END IF;
 entity_id=COALESCE((row_data->>'id')::uuid,(row_data->>'user_id')::uuid);
 INSERT INTO public.audit_logs(project_id,actor_id,entity,entity_id,action)
 VALUES(project,auth.uid(),TG_TABLE_NAME,entity_id,TG_OP);
 RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END $function$;

CREATE TRIGGER audit_projects     AFTER INSERT OR UPDATE           ON public.projects        FOR EACH ROW EXECUTE FUNCTION app_private.audit_change();
CREATE TRIGGER audit_members      AFTER INSERT OR UPDATE OR DELETE ON public.project_members FOR EACH ROW EXECUTE FUNCTION app_private.audit_change();
CREATE TRIGGER audit_applications AFTER INSERT OR UPDATE           ON public.applications    FOR EACH ROW EXECUTE FUNCTION app_private.audit_change();
CREATE TRIGGER audit_environments AFTER INSERT OR UPDATE           ON public.environments    FOR EACH ROW EXECUTE FUNCTION app_private.audit_change();
CREATE TRIGGER audit_invitations  AFTER INSERT OR UPDATE           ON public.invitations     FOR EACH ROW EXECUTE FUNCTION app_private.audit_change();

-- -----------------------------------------------------------------------------
-- RLS auto-enable
--
-- Fires on every DDL command and enables RLS on any new table in `public`.
-- It is scoped to `public` only, so a `blindspot` schema is unaffected — which
-- is part of why aiservice/BE product tables live in their own schema.
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.rls_auto_enable()
 RETURNS event_trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path TO 'pg_catalog'
AS $function$
DECLARE cmd record; tbl name;
BEGIN
  FOR cmd IN
    SELECT * FROM pg_event_trigger_ddl_commands()
    WHERE command_tag IN ('CREATE TABLE', 'CREATE TABLE AS', 'SELECT INTO')
      AND object_type IN ('table','partitioned table')
  LOOP
     IF cmd.schema_name IS NOT NULL AND cmd.schema_name IN ('public')
        AND cmd.schema_name NOT IN ('pg_catalog','information_schema')
        AND cmd.schema_name NOT LIKE 'pg_toast%' AND cmd.schema_name NOT LIKE 'pg_temp%' THEN
      BEGIN
        SELECT c.relname INTO tbl FROM pg_catalog.pg_class c WHERE c.oid = cmd.objid;
        EXECUTE format('alter table if exists %I.%I enable row level security', cmd.schema_name, tbl);
        RAISE LOG 'rls_auto_enable: enabled RLS on %', cmd.object_identity;
      EXCEPTION WHEN OTHERS THEN
        RAISE LOG 'rls_auto_enable: failed to enable RLS on %', cmd.object_identity;
      END;
     ELSE
        RAISE LOG 'rls_auto_enable: skip % (either system schema or not in enforced list: %.)', cmd.object_identity, cmd.schema_name;
     END IF;
  END LOOP;
END;
$function$;

CREATE EVENT TRIGGER ensure_rls ON ddl_command_end EXECUTE FUNCTION public.rls_auto_enable();

-- =============================================================================
-- KNOWN ISSUES in the live schema, recorded here rather than silently fixed
--
-- 1. public.rls_auto_enable() is EXECUTE-able by `anon` and `authenticated`
--    through PostgREST at /rest/v1/rpc/rls_auto_enable. It is an event-trigger
--    function with no business being in the exposed API schema. Low impact —
--    it takes no arguments and fails outside event-trigger context — but it
--    should be REVOKEd from anon/authenticated or moved to app_private.
--      REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM anon, authenticated;
--
-- 2. [RESOLVED 2026-11-05 — see "APPLIED CHANGES" below] public.profiles was
--    never populated; there was no trigger on auth.users. Fixed by
--    on_auth_user_created / app_private.handle_new_user().
--
-- 3. public.profiles RLS is `user_id = auth.uid()` FOR ALL, so a user can read
--    only their own profile and no client can resolve a teammate's display
--    name. Planned fix: BE resolves names server-side rather than loosening it.
--
-- 4. Ownership is recorded twice — projects.owner_id AND a project_members row
--    with role='owner'. can_access() ORs them. Transferring ownership via one
--    and not the other makes them disagree inside an authorization path.
--
-- 5. projects.owner_id is unindexed; see the note in the index section.
--
-- 6. Supabase Auth has leaked-password protection disabled.
-- =============================================================================

-- =============================================================================
-- APPLIED CHANGES
--
-- 2026-11-05 — migration `blindspot_be_prerequisites` (BlindSpotBE B1, Step 1).
-- The only two changes BE is permitted to make to `public`. Everything else
-- in this file still reflects the live schema as it was before this date.
-- =============================================================================

-- 1a. Populate public.profiles on signup.
CREATE OR REPLACE FUNCTION app_private.handle_new_user()
 RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path TO ''
AS $$
BEGIN
  INSERT INTO public.profiles(user_id, display_name)
  VALUES (NEW.id, COALESCE(NULLIF(btrim(NEW.raw_user_meta_data->>'display_name'), ''), ''))
  ON CONFLICT (user_id) DO NOTHING;
  RETURN NEW;
END $$;

CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION app_private.handle_new_user();

-- 1b. Free public.environments from public.applications, add credential
-- columns. application_id stays as a nullable column; dropping it is a
-- separate decision alongside `applications` itself.
ALTER TABLE public.environments ALTER COLUMN application_id DROP NOT NULL;

ALTER TABLE public.environments
  DROP CONSTRAINT environments_project_id_application_id_fkey;

ALTER TABLE public.environments
  ADD CONSTRAINT environments_project_id_fkey
  FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;

ALTER TABLE public.environments
  ADD COLUMN encrypted_credentials text,
  ADD COLUMN revision int NOT NULL DEFAULT 1,
  ADD COLUMN verified_at timestamptz;
-- =============================================================================
