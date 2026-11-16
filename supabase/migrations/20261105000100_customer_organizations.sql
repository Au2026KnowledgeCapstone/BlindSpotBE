-- Supabase-owned tenancy extension. The existing public tenancy and blindspot
-- Alembic head (f11ed461fc25) remain unchanged; public projects/environments are
-- referenced by blindspot foreign keys and must not be moved or recreated.
-- Legacy projects remain organization_id NULL. Apply only after the existing
-- public application_infrastructure migration is verified as already applied;
-- production tenancy and environments must never be recreated from scratch.
-- REVIEW/ROLLOUT GUARD: this additive file assumes the migration ledger records
-- `20261026231753_application_infrastructure` as already applied. The current
-- hosted database was verified by read-only metadata to have the matching public
-- tenancy tables and blindspot Alembic head f11ed461fc25; do not run the baseline
-- SQL against that database. Use the Supabase migration ledger repair workflow
-- only after a reviewed catalog diff confirms its exact schema is present.
CREATE TABLE public.organizations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 owner_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
 name text NOT NULL CHECK(length(btrim(name)) BETWEEN 1 AND 120),
 creation_request_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(owner_id,creation_request_id)
);
-- Retain the verified hosted environment contract: applications are optional;
-- credentials are encrypted at rest and never exposed through the API DTO.
-- Production already has the three extension columns and application nullability;
-- these IF NOT EXISTS clauses support clean installs and pre-extension fixtures.
ALTER TABLE public.environments ALTER COLUMN application_id DROP NOT NULL;
ALTER TABLE public.environments ADD COLUMN IF NOT EXISTS encrypted_credentials text;
ALTER TABLE public.environments ADD COLUMN IF NOT EXISTS revision integer NOT NULL DEFAULT 1 CHECK (revision > 0);
ALTER TABLE public.environments ADD COLUMN IF NOT EXISTS verified_at timestamptz;

CREATE TABLE public.organization_members (
 organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
 user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
 role text NOT NULL CHECK(role IN ('owner','admin','member')),
 PRIMARY KEY(organization_id,user_id)
);
ALTER TABLE public.projects ADD COLUMN organization_id uuid REFERENCES public.organizations(id) ON DELETE SET NULL;
ALTER TABLE public.projects ADD COLUMN creation_request_id uuid;
CREATE UNIQUE INDEX projects_owner_creation_request ON public.projects(owner_id,creation_request_id) WHERE creation_request_id IS NOT NULL;

CREATE FUNCTION app_private.is_org_admin(p_org uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path='' AS $$
 SELECT auth.uid() IS NOT NULL AND EXISTS (
  SELECT 1 FROM public.organization_members WHERE organization_id=p_org AND user_id=auth.uid() AND role IN ('owner','admin'))
$$;
REVOKE ALL ON FUNCTION app_private.is_org_admin(uuid) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION app_private.is_org_admin(uuid) TO authenticated;
CREATE OR REPLACE FUNCTION app_private.can_access(p uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path='' AS $$
 SELECT auth.uid() IS NOT NULL AND EXISTS (SELECT 1 FROM public.projects p WHERE p.id=$1 AND
  (p.owner_id=auth.uid() OR EXISTS(SELECT 1 FROM public.project_members pm WHERE pm.project_id=p.id AND pm.user_id=auth.uid()) OR app_private.is_org_admin(p.organization_id)))
$$;
CREATE OR REPLACE FUNCTION app_private.can_manage(p uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path='' AS $$
 SELECT auth.uid() IS NOT NULL AND EXISTS (SELECT 1 FROM public.projects p WHERE p.id=$1 AND
  (p.owner_id=auth.uid() OR EXISTS(SELECT 1 FROM public.project_members pm WHERE pm.project_id=p.id AND pm.user_id=auth.uid() AND pm.role='admin') OR app_private.is_org_admin(p.organization_id)))
$$;

ALTER TABLE public.organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organization_members ENABLE ROW LEVEL SECURITY;
CREATE POLICY organizations_visible ON public.organizations FOR SELECT TO authenticated USING (
 owner_id=auth.uid() OR EXISTS(SELECT 1 FROM public.organization_members m WHERE m.organization_id=id AND m.user_id=auth.uid()));
CREATE POLICY organization_members_visible ON public.organization_members FOR SELECT TO authenticated USING (
 user_id=auth.uid() OR app_private.is_org_admin(organization_id));
CREATE POLICY profile_project_members ON public.profiles FOR SELECT TO authenticated USING (
 EXISTS (SELECT 1 FROM public.project_members mine WHERE mine.user_id=auth.uid() AND app_private.can_access(mine.project_id)
  AND EXISTS (SELECT 1 FROM public.project_members theirs WHERE theirs.project_id=mine.project_id AND theirs.user_id=profiles.user_id))
 OR EXISTS (SELECT 1 FROM public.organization_members om WHERE om.user_id=auth.uid() AND om.role IN ('owner','admin')
  AND EXISTS (SELECT 1 FROM public.projects p WHERE p.organization_id=om.organization_id AND app_private.can_access(p.id)
   AND EXISTS (SELECT 1 FROM public.project_members theirs WHERE theirs.project_id=p.id AND theirs.user_id=profiles.user_id))));
REVOKE ALL ON public.organizations,public.organization_members FROM PUBLIC,anon,authenticated;
GRANT SELECT ON public.organizations,public.organization_members TO authenticated;

CREATE FUNCTION public.complete_customer_onboarding(p_organization_name text,p_project_name text,p_request_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE uid uuid:=auth.uid(); org public.organizations; proj public.projects;
BEGIN
 IF uid IS NULL OR app_private.verified_email() IS NULL THEN RAISE EXCEPTION 'Verified sign-in required' USING ERRCODE='42501'; END IF;
 IF p_request_id IS NULL OR length(btrim(p_organization_name)) NOT BETWEEN 1 AND 120 OR length(btrim(p_project_name)) NOT BETWEEN 1 AND 120 THEN RAISE EXCEPTION 'Invalid organization or project name' USING ERRCODE='23514'; END IF;
 INSERT INTO public.organizations(owner_id,name,creation_request_id) VALUES(uid,btrim(p_organization_name),p_request_id)
 ON CONFLICT(owner_id,creation_request_id) DO NOTHING;
 SELECT * INTO org FROM public.organizations WHERE owner_id=uid AND creation_request_id=p_request_id;
 INSERT INTO public.organization_members(organization_id,user_id,role) VALUES(org.id,uid,'owner') ON CONFLICT DO NOTHING;
 INSERT INTO public.projects(owner_id,name,organization_id,creation_request_id) VALUES(uid,btrim(p_project_name),org.id,p_request_id)
 ON CONFLICT(owner_id,creation_request_id) WHERE creation_request_id IS NOT NULL DO NOTHING;
 SELECT * INTO proj FROM public.projects WHERE owner_id=uid AND creation_request_id=p_request_id;
 IF proj.organization_id IS DISTINCT FROM org.id THEN RAISE EXCEPTION 'Request already used' USING ERRCODE='23505'; END IF;
 INSERT INTO public.project_members(project_id,user_id,role) VALUES(proj.id,uid,'owner') ON CONFLICT DO NOTHING;
 RETURN jsonb_build_object('organization',to_jsonb(org),'project',to_jsonb(proj));
END $$;
CREATE FUNCTION public.create_project_in_organization(p_organization_id uuid,p_name text,p_description text,p_request_id uuid)
RETURNS public.projects LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE uid uuid:=auth.uid(); result public.projects;
BEGIN
 IF uid IS NULL OR app_private.verified_email() IS NULL THEN RAISE EXCEPTION 'Verified sign-in required' USING ERRCODE='42501'; END IF;
 IF p_request_id IS NULL OR length(btrim(p_name)) NOT BETWEEN 1 AND 120 OR length(COALESCE(p_description,''))>2000 THEN RAISE EXCEPTION 'Invalid project values' USING ERRCODE='23514'; END IF;
 IF NOT app_private.is_org_admin(p_organization_id) THEN RAISE EXCEPTION 'Organization admin required' USING ERRCODE='42501'; END IF;
 INSERT INTO public.projects(owner_id,name,description,organization_id,creation_request_id) VALUES(uid,btrim(p_name),COALESCE(p_description,''),p_organization_id,p_request_id)
 ON CONFLICT(owner_id,creation_request_id) WHERE creation_request_id IS NOT NULL DO NOTHING;
 SELECT * INTO result FROM public.projects WHERE owner_id=uid AND creation_request_id=p_request_id;
 IF result.organization_id IS DISTINCT FROM p_organization_id THEN RAISE EXCEPTION 'Request already used' USING ERRCODE='23505'; END IF;
 INSERT INTO public.project_members(project_id,user_id,role) VALUES(result.id,uid,'owner') ON CONFLICT DO NOTHING;
 RETURN result;
END $$;
REVOKE ALL ON FUNCTION public.complete_customer_onboarding(text,text,uuid),public.create_project_in_organization(uuid,text,text,uuid) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.complete_customer_onboarding(text,text,uuid),public.create_project_in_organization(uuid,text,text,uuid) TO authenticated;
