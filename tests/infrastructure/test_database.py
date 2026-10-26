"""Integration tests against a fresh, disposable PostgreSQL database.
Auth fixture emulates identity claims; does not validate real Supabase JWTs.
"""
import os
import unittest
from pathlib import Path
from uuid import uuid4
import psycopg

ROOT = Path(__file__).resolve().parents[2]
SOCKET = "/home/nala/quoroum-backend/data/ops/mohagany-test-postgres/socket"
A, B, C, D = [str(uuid4()) for _ in range(4)]

class DatabaseSecurityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = "capstone_verified_" + uuid4().hex[:10]
        cls.admin = psycopg.connect(host=SOCKET,port=55432,user="nala",dbname="postgres",autocommit=True)
        cls.admin.execute(psycopg.sql.SQL("CREATE DATABASE {} ENCODING 'UTF8' TEMPLATE template0").format(psycopg.sql.Identifier(cls.db)))
        cls.con = psycopg.connect(host=SOCKET,port=55432,user="nala",dbname=cls.db,autocommit=True)
        cls.con.execute((ROOT/"tests/infrastructure/bootstrap.sql").read_text())
        with cls.con.transaction():
            for f in sorted((ROOT/"supabase/migrations").glob("*.sql")):
                cls.con.execute(f.read_text())
        for uid,email,confirmed in [(A,"owner-a@example.invalid",True),(B,"owner-b@example.invalid",True),(C,"invitee@example.invalid",True),(D,"unverified@example.invalid",False)]:
            cls.con.execute("INSERT INTO auth.users VALUES(%s,%s,CASE WHEN %s THEN now() END)",(uid,email,confirmed))
        cls.pa = cls.as_user(A,"SELECT id FROM public.create_project(%s)",("Alpha",))[0][0]
        cls.pb = cls.as_user(B,"SELECT id FROM public.create_project(%s)",("Beta",))[0][0]
        cls.aa = cls.as_user(A,"INSERT INTO public.applications(project_id,name) VALUES(%s,'App A') RETURNING id",(cls.pa,))[0][0]
        cls.ab = cls.as_user(B,"INSERT INTO public.applications(project_id,name) VALUES(%s,'App B') RETURNING id",(cls.pb,))[0][0]
        cls.ea = cls.as_user(A,"INSERT INTO public.environments(project_id,application_id,name,kind,base_url) VALUES(%s,%s,'Dev','development','https://example.invalid') RETURNING id",(cls.pa,cls.aa))[0][0]
        cls.eb = cls.as_user(B,"INSERT INTO public.environments(project_id,application_id,name,kind,base_url) VALUES(%s,%s,'Dev','development','https://example.invalid') RETURNING id",(cls.pb,cls.ab))[0][0]

    @classmethod
    def as_user(cls,uid,query,params=(),role="authenticated"):
        with cls.con.transaction():
            cls.con.execute(psycopg.sql.SQL("SET LOCAL ROLE {}").format(psycopg.sql.Identifier(role)))
            cls.con.execute("SELECT set_config('request.jwt.claim.sub',%s,true)",(uid or "",))
            cur=cls.con.execute(query,params)
            return cur.fetchall() if cur.description else cur.rowcount

    def denied(self,uid,query,params=(),states=("42501",)):
        with self.assertRaises(psycopg.Error) as result:
            self.as_user(uid,query,params)
        self.assertIn(result.exception.sqlstate,states)

    def test_01_all_tables_have_rls(self):
        rows=self.con.execute("SELECT tablename,rowsecurity FROM pg_tables WHERE schemaname='public'").fetchall()
        self.assertEqual(len(rows),10)
        self.assertTrue(all(enabled for _,enabled in rows),rows)
        self.assertEqual(self.as_user(A,"SELECT current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")[0],("authenticated",False,False))

    def test_02_owner_and_tenant_reads(self):
        self.assertEqual(self.as_user(A,"SELECT id FROM public.projects"),[(self.pa,)])
        self.assertEqual(self.as_user(B,"SELECT id FROM public.projects"),[(self.pb,)])
        self.assertEqual(self.as_user(C,"SELECT id FROM public.projects"),[])
        self.assertEqual(self.as_user(A,"SELECT id FROM public.environments"),[(self.ea,)])
        self.assertEqual(self.as_user(A,"SELECT id FROM public.applications"),[(self.aa,)])
        self.assertEqual(self.as_user(A,"SELECT DISTINCT project_id FROM public.project_members"),[(self.pa,)])

    def test_03_anonymous_and_null_identity_denied(self):
        self.assertEqual(self.as_user(None,"SELECT * FROM public.projects"),[])
        self.denied(None,"SELECT * FROM public.create_project('No identity')",states=("42501",))
        with self.assertRaises(psycopg.Error):
            self.as_user(None,"SELECT * FROM public.create_project('Anonymous')",role="anon")
        with self.assertRaises(psycopg.Error):
            self.as_user(None,"SELECT * FROM public.projects",role="anon")

    def test_04_no_direct_owner_or_membership_escalation(self):
        self.denied(A,"UPDATE public.projects SET owner_id=%s WHERE id=%s",(B,self.pa))
        self.denied(C,"INSERT INTO public.project_members VALUES(%s,%s,'owner')",(self.pa,C))
        self.denied(A,"UPDATE public.project_members SET role='owner' WHERE project_id=%s",(self.pb,))
        self.denied(A,"DELETE FROM public.project_members WHERE project_id=%s",(self.pb,))
        self.denied(A,"INSERT INTO public.projects(owner_id,name) VALUES(%s,'Spoof')",(B,))
        self.assertEqual(self.as_user(A,"UPDATE public.projects SET name='intrusion' WHERE id=%s RETURNING id",(self.pb,)),[])

    def test_05_scoped_writes_and_cross_project_foreign_keys(self):
        self.denied(A,"INSERT INTO public.applications(project_id,name) VALUES(%s,'Intrusion')",(self.pb,))
        self.assertEqual(self.as_user(A,"UPDATE public.environments SET name='Intrusion' WHERE id=%s RETURNING id",(self.eb,)),[])
        self.denied(A,"DELETE FROM public.environments WHERE id=%s",(self.eb,))
        self.denied(A,"INSERT INTO public.environments(project_id,application_id,name,kind,base_url) VALUES(%s,%s,'Bad','staging','https://example.invalid')",(self.pa,self.ab),("23503",))
        self.denied(A,"INSERT INTO public.scans(project_id,environment_id) VALUES(%s,%s)",(self.pa,self.eb),("23503",))
        scan=self.as_user(A,"INSERT INTO public.scans(project_id,environment_id) VALUES(%s,%s) RETURNING id",(self.pa,self.ea))[0][0]
        self.denied(A,"UPDATE public.scans SET status='passed' WHERE id=%s",(scan,))
        self.denied(A,"INSERT INTO public.test_results(project_id,scan_id,name,status) VALUES(%s,%s,'Fake','passed')",(self.pa,scan))
        self.con.execute("INSERT INTO public.test_results(project_id,scan_id,name,status) VALUES(%s,%s,'Worker result','passed')",(self.pa,scan))
        self.assertEqual(len(self.as_user(A,"SELECT id FROM public.test_results WHERE scan_id=%s",(scan,))),1)
        self.assertEqual(self.as_user(B,"SELECT id FROM public.test_results WHERE scan_id=%s",(scan,)),[])

    def test_06_invitation_permissions_expiry_replay_and_verified_email(self):
        self.denied(C,"SELECT id FROM public.invite_member(%s,'invitee@example.invalid')",(self.pa,))
        self.denied(A,"SELECT id FROM public.invite_member(%s,'invitee@example.invalid')",(self.pb,))
        invite=self.as_user(A,"SELECT id FROM public.invite_member(%s,'invitee@example.invalid')",(self.pa,))[0][0]
        self.denied(B,"SELECT * FROM public.accept_invitation(%s)",(invite,))
        self.assertEqual(self.as_user(B,"SELECT id FROM public.invitations WHERE id=%s",(invite,)),[])
        self.assertEqual(self.as_user(C,"SELECT role FROM public.accept_invitation(%s)",(invite,)),[("member",)])
        self.assertIn((self.pa,),self.as_user(C,"SELECT id FROM public.projects"))
        self.denied(C,"SELECT * FROM public.accept_invitation(%s)",(invite,))
        self.denied(C,"UPDATE public.project_members SET role='admin' WHERE user_id=%s",(C,))
        self.denied(C,"SELECT * FROM public.invite_member(%s,'other@example.invalid','admin')",(self.pa,))
        unverified=self.as_user(A,"SELECT id FROM public.invite_member(%s,'unverified@example.invalid')",(self.pa,))[0][0]
        self.denied(D,"SELECT * FROM public.accept_invitation(%s)",(unverified,))
        expired=self.as_user(A,"SELECT id FROM public.invite_member(%s,'owner-b@example.invalid')",(self.pa,))[0][0]
        self.con.execute("UPDATE public.invitations SET expires_at=now()-interval '1 second' WHERE id=%s",(expired,))
        self.denied(B,"SELECT * FROM public.accept_invitation(%s)",(expired,))
        self.denied(A,"SELECT * FROM public.invite_member(%s,'bad-email')",(self.pa,),("23514",))
        self.denied(A,"SELECT * FROM public.invite_member(%s,'owner-b@example.invalid','owner')",(self.pa,),("23514",))

    def test_07_notifications_and_audit_are_scoped(self):
        n=self.con.execute("INSERT INTO public.notifications(user_id,project_id,message) VALUES(%s,%s,'Private') RETURNING id",(A,self.pa)).fetchone()[0]
        self.assertEqual(self.as_user(B,"SELECT id FROM public.notifications WHERE id=%s",(n,)),[])
        self.assertEqual(len(self.as_user(A,"UPDATE public.notifications SET read_at=now() WHERE id=%s RETURNING id",(n,))),1)
        self.denied(A,"UPDATE public.notifications SET user_id=%s WHERE id=%s",(B,n))
        self.denied(A,"INSERT INTO public.audit_logs(project_id,actor_id,entity,entity_id,action) VALUES(%s,%s,'fake',%s,'INSERT')",(self.pa,A,self.pa))
        self.denied(A,"DELETE FROM public.audit_logs WHERE project_id=%s",(self.pa,))
        self.assertGreater(len(self.as_user(A,"SELECT id FROM public.audit_logs WHERE project_id=%s",(self.pa,))),0)
        self.assertEqual(self.as_user(B,"SELECT id FROM public.audit_logs WHERE project_id=%s",(self.pa,)),[])

    def test_08_profiles_and_name_validation(self):
        self.as_user(A,"INSERT INTO public.profiles(user_id,display_name) VALUES(%s,'Owner A')",(A,))
        self.assertEqual(self.as_user(B,"SELECT user_id FROM public.profiles"),[])
        self.denied(A,"INSERT INTO public.profiles(user_id,display_name) VALUES(%s,'Impersonation')",(B,))
        self.denied(A,"SELECT * FROM public.create_project('   ')",states=("23514",))
        self.denied(A,"SELECT * FROM public.create_project(%s)",("x"*121,),("23514",))

    def test_09_privileged_project_cleanup_cascades_without_orphan_audit(self):
        project=self.as_user(A,"SELECT id FROM public.create_project('Cleanup')")[0][0]
        app=self.as_user(A,"INSERT INTO public.applications(project_id,name) VALUES(%s,'Cleanup app') RETURNING id",(project,))[0][0]
        self.as_user(A,"INSERT INTO public.environments(project_id,application_id,name,kind,base_url) VALUES(%s,%s,'Cleanup env','staging','https://example.invalid')",(project,app))
        self.denied(A,"DELETE FROM public.projects WHERE id=%s",(project,))
        self.con.execute("DELETE FROM public.projects WHERE id=%s",(project,))
        for table in ["project_members","applications","environments","audit_logs"]:
            self.assertEqual(self.con.execute("SELECT count(*) FROM public."+table+" WHERE project_id=%s",(project,)).fetchone()[0],0)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        cls.admin.execute(psycopg.sql.SQL("DROP DATABASE {}").format(psycopg.sql.Identifier(cls.db)))
        cls.admin.close()

if __name__=="__main__": unittest.main(verbosity=2)
