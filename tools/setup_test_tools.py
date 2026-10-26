#!/usr/bin/env python3
"""Install a pinned PostgREST binary in .tools, without root/system changes."""
import hashlib
import io
import json
from pathlib import Path
import platform
import tarfile
import urllib.request

VERSION = "v16.5"
ROOT = Path(__file__).resolve().parents[1]
if platform.system() != "Linux" or platform.machine() not in ("x86_64","aarch64"):
    raise SystemExit("Use POSTGREST_BIN with a compatible PostgREST installation on this platform.")
arch="x86-64" if platform.machine()=="x86_64" else "aarch64"
with urllib.request.urlopen("https://api.github.com/repos/PostgREST/postgrest/releases/tags/"+VERSION,timeout=20) as response:
    release=json.load(response)
asset=next(a for a in release["assets"] if a["name"]==f"postgrest-{VERSION}-linux-static-{arch}.tar.xz")
with urllib.request.urlopen(asset["browser_download_url"],timeout=30) as response:
    archive=response.read()
digest="sha256:"+hashlib.sha256(archive).hexdigest()
if asset.get("digest") != digest:
    raise SystemExit("Release digest absent or mismatched; no executable installed.")
target=ROOT/".tools/postgrest"
target.parent.mkdir(exist_ok=True)
with tarfile.open(fileobj=io.BytesIO(archive),mode="r:xz") as tar:
    member=next(m for m in tar.getmembers() if m.isfile() and m.name.rsplit("/",1)[-1]=="postgrest")
    target.write_bytes(tar.extractfile(member).read())
target.chmod(0o700)
print("Installed verified PostgREST "+VERSION+" in .tools/postgrest")
