-- Application schema only. Supabase owns auth.users; never replace or alter it.
CREATE SCHEMA app_private;
REVOKE ALL ON SCHEMA app_private FROM PUBLIC;
GRANT USAGE ON SCHEMA app_private TO authenticated;
CREATE TABLE public.profiles (
 user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
 display_name text NOT NULL DEFAULT '' CHECK (length(display_name)<=100),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.projects (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 owner_id uuid NOT NULL REFERENCES auth.users(id),
 name text NOT NULL CHECK(length(btrim(name)) BETWEEN 1 AND 120),
 description text NOT NULL DEFAULT '' CHECK(length(description)<=2000),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.project_members (
 project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
 user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
 role text NOT NULL CHECK(role IN ('owner','admin','member')),
 PRIMARY KEY(project_id,user_id)
);
CREATE TABLE public.applications (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
 name text NOT NULL CHECK(length(btrim(name)) BETWEEN 1 AND 120),
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(project_id,id)
);
CREATE TABLE public.environments (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 project_id uuid NOT NULL,
 application_id uuid NOT NULL,
 name text NOT NULL CHECK(length(btrim(name)) BETWEEN 1 AND 120),
 kind text NOT NULL CHECK(kind IN ('development','staging','production')),
 base_url text NOT NULL CHECK(base_url ~ '^https?://[^[:space:]]+$' AND length(base_url)<=2048),
 credential_reference text CHECK(length(credential_reference)<=200),
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(project_id,application_id) REFERENCES public.applications(project_id,id) ON DELETE CASCADE,
 UNIQUE(project_id,id)
);
CREATE TABLE public.scans (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 project_id uuid NOT NULL,
 environment_id uuid NOT NULL,
 requested_by uuid NOT NULL DEFAULT auth.uid() REFERENCES auth.users(id),
 status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','passed','failed','cancelled')),
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(project_id,environment_id) REFERENCES public.environments(project_id,id) ON DELETE CASCADE,
 UNIQUE(project_id,id)
);
CREATE TABLE public.test_results (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 project_id uuid NOT NULL,
 scan_id uuid NOT NULL,
 name text NOT NULL CHECK(length(btrim(name)) BETWEEN 1 AND 200),
 status text NOT NULL CHECK(status IN ('passed','failed','skipped')),
 summary text NOT NULL DEFAULT '' CHECK(length(summary)<=10000),
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(project_id,scan_id) REFERENCES public.scans(project_id,id) ON DELETE CASCADE
);
CREATE TABLE public.notifications (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
 project_id uuid REFERENCES public.projects(id) ON DELETE CASCADE,
 message text NOT NULL CHECK(length(message)<=1000),
 read_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.invitations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
 email text NOT NULL CHECK(email=lower(btrim(email)) AND email ~ '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$'),
 role text NOT NULL CHECK(role IN ('admin','member')),
 invited_by uuid NOT NULL REFERENCES auth.users(id),
 expires_at timestamptz NOT NULL DEFAULT now()+interval '7 days',
 accepted_by uuid REFERENCES auth.users(id),
 accepted_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(),
 CHECK((accepted_by IS NULL)=(accepted_at IS NULL))
);
CREATE UNIQUE INDEX invitations_pending_email ON public.invitations(project_id,email) WHERE accepted_at IS NULL;
CREATE TABLE public.audit_logs (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
 actor_id uuid REFERENCES auth.users(id) ON DELETE SET NULL,
 entity text NOT NULL,
 entity_id uuid NOT NULL,
 action text NOT NULL CHECK(action IN ('INSERT','UPDATE','DELETE')),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX project_members_user ON public.project_members(user_id,project_id);
CREATE INDEX applications_project ON public.applications(project_id);
CREATE INDEX environments_project ON public.environments(project_id);
CREATE INDEX scans_project ON public.scans(project_id,created_at DESC);
CREATE INDEX test_results_scan ON public.test_results(project_id,scan_id);
CREATE INDEX notifications_user ON public.notifications(user_id,created_at DESC);
CREATE INDEX invitations_email ON public.invitations(email);
CREATE INDEX audit_logs_project ON public.audit_logs(project_id,created_at DESC);

-- Helpers use caller identity only, not a caller-supplied user ID.
-- Definer reads avoid recursive membership RLS. Fixed empty search path.
CREATE FUNCTION app_private.can_access(p uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path='' AS $$
 SELECT auth.uid() IS NOT NULL AND (
 EXISTS(SELECT 1 FROM public.projects WHERE id=p AND owner_id=auth.uid()) OR
 EXISTS(SELECT 1 FROM public.project_members WHERE project_id=p AND user_id=auth.uid()))
$$;
CREATE FUNCTION app_private.can_manage(p uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path='' AS $$
 SELECT auth.uid() IS NOT NULL AND (
 EXISTS(SELECT 1 FROM public.projects WHERE id=p AND owner_id=auth.uid()) OR
 EXISTS(SELECT 1 FROM public.project_members WHERE project_id=p AND user_id=auth.uid() AND role='admin'))
$$;
CREATE FUNCTION app_private.verified_email() RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path='' AS $$
 SELECT lower(email) FROM auth.users WHERE id=auth.uid() AND email_confirmed_at IS NOT NULL
$$;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA app_private FROM PUBLIC;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA app_private TO authenticated;

ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.project_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.applications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.environments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.scans ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.test_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invitations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY profile_self ON public.profiles FOR ALL TO authenticated USING(user_id=auth.uid()) WITH CHECK(user_id=auth.uid());
CREATE POLICY project_read ON public.projects FOR SELECT TO authenticated USING(app_private.can_access(id));
CREATE POLICY project_update ON public.projects FOR UPDATE TO authenticated USING(app_private.can_manage(id)) WITH CHECK(app_private.can_manage(id));
CREATE POLICY member_read ON public.project_members FOR SELECT TO authenticated USING(app_private.can_access(project_id));
CREATE POLICY application_read ON public.applications FOR SELECT TO authenticated USING(app_private.can_access(project_id));
CREATE POLICY application_insert ON public.applications FOR INSERT TO authenticated WITH CHECK(app_private.can_manage(project_id));
CREATE POLICY application_update ON public.applications FOR UPDATE TO authenticated USING(app_private.can_manage(project_id)) WITH CHECK(app_private.can_manage(project_id));
CREATE POLICY environment_read ON public.environments FOR SELECT TO authenticated USING(app_private.can_access(project_id));
CREATE POLICY environment_insert ON public.environments FOR INSERT TO authenticated WITH CHECK(app_private.can_manage(project_id));
CREATE POLICY environment_update ON public.environments FOR UPDATE TO authenticated USING(app_private.can_manage(project_id)) WITH CHECK(app_private.can_manage(project_id));
CREATE POLICY scan_read ON public.scans FOR SELECT TO authenticated USING(app_private.can_access(project_id));
CREATE POLICY scan_insert ON public.scans FOR INSERT TO authenticated WITH CHECK(app_private.can_access(project_id) AND requested_by=auth.uid() AND status='queued');
CREATE POLICY result_read ON public.test_results FOR SELECT TO authenticated USING(app_private.can_access(project_id));
CREATE POLICY notification_self ON public.notifications FOR SELECT TO authenticated USING(user_id=auth.uid());
CREATE POLICY notification_read_state ON public.notifications FOR UPDATE TO authenticated USING(user_id=auth.uid()) WITH CHECK(user_id=auth.uid());
CREATE POLICY invitation_read ON public.invitations FOR SELECT TO authenticated USING(app_private.can_manage(project_id) OR email=app_private.verified_email());
CREATE POLICY audit_read ON public.audit_logs FOR SELECT TO authenticated USING(app_private.can_manage(project_id));

-- Remove Supabase default API grants before applying explicit least privilege.
REVOKE ALL ON public.profiles,public.projects,public.project_members,public.applications,public.environments,public.scans,public.test_results,public.notifications,public.invitations,public.audit_logs FROM anon,authenticated;
GRANT SELECT ON public.profiles,public.projects,public.project_members,public.applications,public.environments,public.scans,public.test_results,public.notifications,public.invitations,public.audit_logs TO authenticated;
GRANT INSERT(user_id,display_name),UPDATE(display_name) ON public.profiles TO authenticated;
GRANT UPDATE(name,description) ON public.projects TO authenticated;
GRANT INSERT(project_id,name),UPDATE(name) ON public.applications TO authenticated;
GRANT INSERT(project_id,application_id,name,kind,base_url,credential_reference),UPDATE(name,kind,base_url,credential_reference) ON public.environments TO authenticated;
GRANT INSERT(project_id,environment_id) ON public.scans TO authenticated;
GRANT UPDATE(read_at) ON public.notifications TO authenticated;
-- No direct project/member/invitation/audit/result writes by browser clients.

CREATE FUNCTION public.create_project(p_name text,p_description text DEFAULT '') RETURNS public.projects
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE result public.projects;
BEGIN
 IF auth.uid() IS NULL THEN RAISE EXCEPTION 'Authentication required' USING ERRCODE='42501'; END IF;
 INSERT INTO public.projects(owner_id,name,description) VALUES(auth.uid(),btrim(p_name),p_description) RETURNING * INTO result;
 INSERT INTO public.project_members(project_id,user_id,role) VALUES(result.id,auth.uid(),'owner');
 RETURN result;
END $$;
CREATE FUNCTION public.invite_member(p_project_id uuid,p_email text,p_role text DEFAULT 'member') RETURNS public.invitations
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
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
END $$;
CREATE FUNCTION public.accept_invitation(p_invitation_id uuid) RETURNS public.project_members
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
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
END $$;
REVOKE ALL ON FUNCTION public.create_project(text,text),public.invite_member(uuid,text,text),public.accept_invitation(uuid) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.create_project(text,text),public.invite_member(uuid,text,text),public.accept_invitation(uuid) TO authenticated;

CREATE FUNCTION app_private.audit_change() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
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
END $$;
REVOKE ALL ON FUNCTION app_private.audit_change() FROM PUBLIC,authenticated;
CREATE TRIGGER audit_projects AFTER INSERT OR UPDATE ON public.projects FOR EACH ROW EXECUTE FUNCTION app_private.audit_change();
CREATE TRIGGER audit_members AFTER INSERT OR UPDATE OR DELETE ON public.project_members FOR EACH ROW EXECUTE FUNCTION app_private.audit_change();
CREATE TRIGGER audit_applications AFTER INSERT OR UPDATE ON public.applications FOR EACH ROW EXECUTE FUNCTION app_private.audit_change();
CREATE TRIGGER audit_environments AFTER INSERT OR UPDATE ON public.environments FOR EACH ROW EXECUTE FUNCTION app_private.audit_change();
CREATE TRIGGER audit_invitations AFTER INSERT OR UPDATE ON public.invitations FOR EACH ROW EXECUTE FUNCTION app_private.audit_change();
