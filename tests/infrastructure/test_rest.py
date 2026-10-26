"""HTTP integration: genuine signed JWT -> PostgREST role -> PostgreSQL RLS.
Uses synthetic local identities, not hosted Supabase sessions.
"""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import time
import unittest
import urllib.error
import urllib.request
import test_database as database

class RestSecurityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = database.DatabaseSecurityTest
        cls.fixture.setUpClass()
        cls.secret = secrets.token_urlsafe(48)
        cls.base = Path(__file__).resolve().parents[2]
        with socket.socket() as sock:
            sock.bind(("127.0.0.1",0))
            cls.port=sock.getsockname()[1]
        env=dict(os.environ)
        env.update({
            "PGRST_DB_URI": f"postgresql://nala@/{cls.fixture.db}?host={database.SOCKET}&port=55432",
            "PGRST_DB_SCHEMAS":"public","PGRST_DB_ANON_ROLE":"anon",
            "PGRST_SERVER_HOST":"127.0.0.1","PGRST_SERVER_PORT":str(cls.port),
            "PGRST_JWT_SECRET":cls.secret,
            "PGRST_DB_POOL":"2",
        })
        cls.log=(cls.base/".tools/rest-test.log").open("w")
        cls.server=subprocess.Popen([os.getenv("POSTGREST_BIN",str(cls.base/".tools/postgrest"))],env=env,stdout=cls.log,stderr=cls.log)
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{cls.port}/",timeout=.5).close()
                break
            except (OSError,urllib.error.URLError): time.sleep(.1)
        else:
            cls.server.terminate()
            raise RuntimeError("Local PostgREST did not become ready")

    @classmethod
    def token(cls,uid,secret=None,expiry=None):
        def enc(obj): return base64.urlsafe_b64encode(json.dumps(obj,separators=(",",":")).encode()).rstrip(b"=")
        header=enc({"alg":"HS256","typ":"JWT"})
        payload=enc({"role":"authenticated","sub":uid,"exp":expiry or int(time.time())+300})
        body=header+b"."+payload
        signature=base64.urlsafe_b64encode(hmac.new((secret or cls.secret).encode(),body,hashlib.sha256).digest()).rstrip(b"=")
        return (body+b"."+signature).decode()

    def request(self,path,method="GET",body=None,token=None):
        headers={"Content-Type":"application/json"}
        if token: headers["Authorization"]="Bearer "+token
        req=urllib.request.Request(f"http://127.0.0.1:{self.port}"+path,method=method,headers=headers,data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req,timeout=5) as response:
                data=response.read()
                return response.status,json.loads(data) if data else None
        except urllib.error.HTTPError as e:
            return e.code,json.loads(e.read())

    def test_valid_identity_can_create_and_read_persisted_project(self):
        status,result=self.request("/rpc/create_project","POST",{"p_name":"Persisted over HTTP"},self.token(database.A))
        self.assertEqual(status,200,result)
        self.assertEqual(result["owner_id"],database.A)
        pid=result["id"]
        # Fresh HTTP transaction verifies persistence rather than an echoed request.
        status,own=self.request("/projects?id=eq."+pid,token=self.token(database.A))
        self.assertEqual(status,200)
        self.assertEqual(len(own),1)
        status,other=self.request("/projects?id=eq."+pid,token=self.token(database.B))
        self.assertEqual((status,other),(200,[]))
        count=self.fixture.con.execute("SELECT count(*) FROM public.projects WHERE id=%s",(pid,)).fetchone()[0]
        self.assertEqual(count,1)

    def test_forged_expired_anonymous_tokens_and_extra_owner_argument_fail(self):
        status,_=self.request("/rpc/create_project","POST",{"p_name":"Forged"},self.token(database.A,secret="wrong"*10))
        self.assertEqual(status,401)
        status,_=self.request("/rpc/create_project","POST",{"p_name":"Expired"},self.token(database.A,expiry=int(time.time())-60))
        self.assertEqual(status,401)
        status,_=self.request("/rpc/create_project","POST",{"p_name":"Anonymous"})
        self.assertIn(status,(401,403))
        status,_=self.request("/rpc/create_project","POST",{"p_name":"Spoof","owner_id":database.B},self.token(database.A))
        self.assertEqual(status,404)
        status,_=self.request("/project_members","POST",{"project_id":str(self.fixture.pa),"user_id":database.C,"role":"owner"},self.token(database.C))
        self.assertEqual(status,403)

    def test_http_invite_accept_and_audit_visibility(self):
        status,invitation=self.request("/rpc/invite_member","POST",{"p_project_id":str(self.fixture.pa),"p_email":"invitee@example.invalid"},self.token(database.A))
        self.assertEqual(status,200,invitation)
        status,_=self.request("/rpc/accept_invitation","POST",{"p_invitation_id":invitation["id"]},self.token(database.B))
        self.assertEqual(status,403)
        status,member=self.request("/rpc/accept_invitation","POST",{"p_invitation_id":invitation["id"]},self.token(database.C))
        self.assertEqual(status,200,member)
        self.assertEqual(member["role"],"member")
        status,_=self.request("/rpc/accept_invitation","POST",{"p_invitation_id":invitation["id"]},self.token(database.C))
        self.assertEqual(status,403)
        status,audit=self.request("/audit_logs?project_id=eq."+str(self.fixture.pa),token=self.token(database.B))
        self.assertEqual((status,audit),(200,[]))

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.wait(timeout=5)
        cls.log.close()
        cls.fixture.tearDownClass()

if __name__=="__main__": unittest.main(verbosity=2)
