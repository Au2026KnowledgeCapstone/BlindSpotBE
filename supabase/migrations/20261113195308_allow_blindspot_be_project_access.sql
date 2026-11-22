-- The backend authenticates users itself and enforces project membership in ProjectAccess.
-- Its direct database session has no end-user JWT claims, so the browser-facing
-- authenticated policies would otherwise hide every project from blindspot_be.
-- Keep RLS enabled and grant access only to this server-side role; browser users
-- continue to be governed by the existing authenticated policies.
CREATE POLICY blindspot_be_project_read
    ON public.projects FOR SELECT TO blindspot_be
    USING (true);

CREATE POLICY blindspot_be_membership_read
    ON public.project_members FOR SELECT TO blindspot_be
    USING (true);

GRANT SELECT ON public.environments TO blindspot_be;

CREATE POLICY blindspot_be_environment_access
    ON public.environments FOR ALL TO blindspot_be
    USING (true)
    WITH CHECK (true);
