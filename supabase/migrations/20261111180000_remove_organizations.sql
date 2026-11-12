-- Removes the organizations extension added in
-- 20261105000100_customer_organizations.sql. Organizations never grew real
-- management functionality (no rename/delete, no org-level member
-- management, no settings/billing) and only added permission-check
-- complexity with no corresponding product surface to justify it. This is a
-- deliberate, reviewed product decision to remove the concept entirely, not
-- an unreviewed cleanup.

-- Revert to the pre-organization project_members-only authorization check.
CREATE OR REPLACE FUNCTION app_private.can_access(p uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path='' AS $$
 SELECT auth.uid() IS NOT NULL AND (
 EXISTS(SELECT 1 FROM public.projects WHERE id=p AND owner_id=auth.uid()) OR
 EXISTS(SELECT 1 FROM public.project_members WHERE project_id=p AND user_id=auth.uid()))
$$;
CREATE OR REPLACE FUNCTION app_private.can_manage(p uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path='' AS $$
 SELECT auth.uid() IS NOT NULL AND (
 EXISTS(SELECT 1 FROM public.projects WHERE id=p AND owner_id=auth.uid()) OR
 EXISTS(SELECT 1 FROM public.project_members WHERE project_id=p AND user_id=auth.uid() AND role='admin'))
$$;

-- Teammate profile visibility keeps its direct shared-project clause; only
-- the organization-wide admin clause is removed.
ALTER POLICY profile_project_members ON public.profiles USING (
 EXISTS (SELECT 1 FROM public.project_members mine WHERE mine.user_id=auth.uid() AND app_private.can_access(mine.project_id)
  AND EXISTS (SELECT 1 FROM public.project_members theirs WHERE theirs.project_id=mine.project_id AND theirs.user_id=profiles.user_id)));

-- creation_request_id only ever served the two onboarding RPCs' idempotent
-- retry contract below; the plain create_project RPC never used it.
ALTER TABLE public.projects DROP COLUMN organization_id;
ALTER TABLE public.projects DROP COLUMN creation_request_id;

-- CASCADE here only removes objects that exist solely because of these two
-- tables (their own policies, and organization_members' FK to organizations)
-- — both tables are being removed completely, so that's everything it drops.
DROP TABLE public.organization_members, public.organizations CASCADE;

DROP FUNCTION app_private.is_org_admin(uuid);
DROP FUNCTION public.complete_customer_onboarding(text,text,uuid);
DROP FUNCTION public.create_project_in_organization(uuid,text,text,uuid);
