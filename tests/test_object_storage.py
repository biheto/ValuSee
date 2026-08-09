from io import BytesIO

import pytest
from botocore.exceptions import ClientError

from app.core import object_storage


class _Body(BytesIO):
    closed_by_reader = False

    def close(self) -> None:
        self.closed_by_reader = True
        super().close()


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, "HeadBucket")


def test_ensure_bucket_creates_only_when_missing(monkeypatch):
    class Client:
        created = False

        def head_bucket(self, **_kwargs):
            raise _client_error("404")

        def create_bucket(self, **_kwargs):
            self.created = True

    client = Client()
    monkeypatch.setattr(object_storage, "_s3_client", lambda: client)
    object_storage.ensure_bucket_exists()
    assert client.created is True


def test_ensure_bucket_does_not_hide_permission_failure(monkeypatch):
    class Client:
        def head_bucket(self, **_kwargs):
            raise _client_error("AccessDenied")

    monkeypatch.setattr(object_storage, "_s3_client", lambda: Client())
    with pytest.raises(ClientError):
        object_storage.ensure_bucket_exists()


def test_read_s3_object_closes_response_body(monkeypatch):
    body = _Body(b"private-object")

    class Client:
        def get_object(self, **_kwargs):
            return {"Body": body}

    monkeypatch.setattr(object_storage, "_s3_client", lambda: Client())
    assert object_storage.read_stored_object("s3", "account-avatars/a.png") == b"private-object"
    assert body.closed_by_reader is True


def test_read_local_object_rejects_path_outside_attachment_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    outside = tmp_path / "private.txt"
    outside.write_bytes(b"secret")
    assert object_storage.read_stored_object("local", "private.txt") is None

