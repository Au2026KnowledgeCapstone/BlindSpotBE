"""Opaque private objects, one directory (or bucket) per kind.

Kind determines the credential boundary, not the key format: keys stay flat
32-hex regardless of backend, and job/project scoping travels as metadata, not
as a path prefix.
"""
import hashlib
import os
import re
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

from app.core.config import get_settings
from app.core.errors import ServiceError

MAX_OBJECT_BYTES = 10 * 1024 * 1024
Kind = Literal["document", "evidence"]
_SUBDIR = {"document": "documents", "evidence": "evidence"}


class ObjectStore(Protocol):
    def put(self, data: bytes, *, metadata: dict[str, str] | None = None) -> str: ...
    def read(self, key: str, expected_sha: str | None = None) -> bytes: ...
    def present(self, key: str) -> None: ...
    def remove(self, key: str) -> None: ...


class LocalStore:
    """Today's filesystem behaviour, unchanged."""

    def __init__(self, directory: str) -> None:
        self.root = Path(directory).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def path(self, key: str) -> Path:
        if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{32}", key):
            raise ServiceError("not_found", "Private object is unavailable.", 404)
        path = self.root / key
        if path.is_symlink() or path.resolve().parent != self.root:
            raise ServiceError("not_found", "Private object is unavailable.", 404)
        return path

    def put(self, data: bytes, *, metadata: dict[str, str] | None = None) -> str:
        if not data or len(data) > MAX_OBJECT_BYTES:
            raise ServiceError("invalid_upload", "Objects must contain 1 byte to 10 MiB.", 413)
        key = uuid4().hex
        with self.path(key).open("xb") as output:
            os.chmod(output.name, 0o600)
            output.write(data)
        return key

    def remove(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)

    # Kept alongside present()/read() through the step 1->2 transition: grant()
    # and download() still call this directly until step 2 moves the integrity
    # check from grant-time to download-time.
    def available(self, key: str, expected_sha: str | None = None) -> Path:
        path = self.path(key)
        if not path.is_file() or path.stat().st_size > MAX_OBJECT_BYTES:
            raise ServiceError("not_found", "Private object is unavailable.", 404)
        if expected_sha and hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha:
            raise ServiceError("artifact_corrupt", "Private object integrity check failed.", 409)
        return path

    def read(self, key: str, expected_sha: str | None = None) -> bytes:
        return self.available(key, expected_sha).read_bytes()

    def present(self, key: str) -> None:
        self.available(key)


def store_for(kind: Kind) -> ObjectStore:
    directory = get_settings().private_storage_dir
    if not directory:
        raise ServiceError("storage_unavailable", "Private storage is not configured.", 503)
    return LocalStore(str(Path(directory) / _SUBDIR[kind]))
