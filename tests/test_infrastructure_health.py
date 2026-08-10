from app.core import infrastructure


class _S3Client:
    def __init__(self):
        self.bucket = ""

    def head_bucket(self, *, Bucket: str) -> None:
        self.bucket = Bucket


def test_s3_health_runs_for_aws_bucket_without_custom_endpoint(monkeypatch):
    client = _S3Client()
    monkeypatch.delenv("S3_ENDPOINT_URL", raising=False)
    monkeypatch.setenv("S3_BUCKET", "valuesee-private")
    monkeypatch.setattr("boto3.client", lambda *_args, **_kwargs: client)

    result = infrastructure.infrastructure_health()

    assert result["object_storage"] == {"status": "ok"}
    assert client.bucket == "valuesee-private"
