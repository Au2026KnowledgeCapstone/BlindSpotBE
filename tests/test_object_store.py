"""One contract, two backends. No network, emulator or credential required."""
import hashlib

import pytest
from google.api_core import exceptions as api_exceptions

from app.core.errors import ServiceError
from app.services import object_store
from app.services.object_store import MAX_OBJECT_BYTES, GCSStore, LocalStore


class FakeBlob:
    def __init__(self, objects, key):
        self._objects = objects
        self.name = key
        self.metadata = None
        self.size = None

    def upload_from_string(self, data, content_type=None, if_generation_match=None):
        if if_generation_match == 0 and self.name in self._objects:
            raise api_exceptions.PreconditionFailed("already exists")
        self._objects[self.name] = {"data": data, "metadata": dict(self.metadata or {})}
        self.size = len(data)

    def reload(self):
        stored = self._objects.get(self.name)
        if stored is None:
            raise api_exceptions.NotFound("no such object")
        self.size = len(stored["data"])
        self.metadata = dict(stored["metadata"])

    def download_as_bytes(self):
        stored = self._objects.get(self.name)
        if stored is None:
            raise api_exceptions.NotFound("no such object")
        return stored["data"]

    def delete(self):
        if self.name not in self._objects:
            raise api_exceptions.NotFound("no such object")
        del self._objects[self.name]


class FakeBucket:
    def __init__(self, objects):
        self._objects = objects
        self.blob_calls = []

    def blob(self, key):
        self.blob_calls.append(key)
        return FakeBlob(self._objects, key)


class FakeClient:
    def __init__(self, objects):
        self._objects = objects

    def bucket(self, name):
        return FakeBucket(self._objects)


@pytest.fixture(params=["local", "gcs"])
def store(request, tmp_path, monkeypatch):
    if request.param == "local":
        return LocalStore(str(tmp_path / "objects"))
    objects = {}
    monkeypatch.setattr(object_store.storage, "Client", lambda *a, **k: FakeClient(objects))
    return GCSStore("test-bucket")


def test_round_trip(store):
    key = store.put(b"hello world", metadata={"job_id": "abc"})
    assert store.read(key) == b"hello world"
    store.present(key)  # must not raise


def test_one_byte_boundary(store):
    key = store.put(b"x")
    assert store.read(key) == b"x"


def test_ten_mib_boundary(store):
    data = b"x" * MAX_OBJECT_BYTES
    key = store.put(data)
    assert store.read(key) == data


def test_over_cap_rejected_on_write(store):
    with pytest.raises(ServiceError) as exc:
        store.put(b"x" * (MAX_OBJECT_BYTES + 1))
    assert exc.value.status_code == 413


def test_empty_rejected_on_write(store):
    with pytest.raises(ServiceError) as exc:
        store.put(b"")
    assert exc.value.status_code == 413


def test_sha256_mismatch_is_409(store):
    key = store.put(b"actual bytes")
    with pytest.raises(ServiceError) as exc:
        store.read(key, expected_sha=hashlib.sha256(b"other bytes").hexdigest())
    assert exc.value.status_code == 409
    assert exc.value.code == "artifact_corrupt"


def test_sha256_match_reads_through(store):
    data = b"actual bytes"
    key = store.put(data)
    assert store.read(key, expected_sha=hashlib.sha256(data).hexdigest()) == data


def test_missing_key_is_404(store):
    with pytest.raises(ServiceError) as exc:
        store.read("0" * 32)
    assert exc.value.status_code == 404
    with pytest.raises(ServiceError) as exc:
        store.present("0" * 32)
    assert exc.value.status_code == 404


def test_remove_of_absent_key_is_silent(store):
    store.remove("0" * 32)  # must not raise


@pytest.mark.parametrize("key", ["../.env", "not-hex", "x" * 32, "", "a" * 31, "a" * 33])
def test_malformed_key_is_404_before_any_io(store, key):
    with pytest.raises(ServiceError) as exc:
        store.present(key)
    assert exc.value.status_code == 404
    with pytest.raises(ServiceError) as exc:
        store.read(key)
    assert exc.value.status_code == 404
    with pytest.raises(ServiceError) as exc:
        store.remove(key)
    assert exc.value.status_code == 404
    if isinstance(store, GCSStore):
        assert store._bucket.blob_calls == []
