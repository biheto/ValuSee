from __future__ import annotations

import os
from pathlib import Path


def _s3_client():
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=os.getenv("S3_ENDPOINT_URL", "").strip() or None,
        aws_access_key_id=os.getenv("S3_ACCESS_KEY"),
        aws_secret_access_key=os.getenv("S3_SECRET_KEY"),
        region_name=os.getenv("S3_REGION", "us-east-1"),
    )


def ensure_bucket_exists() -> None:
    from botocore.exceptions import ClientError

    bucket = os.getenv("S3_BUCKET", "valuesee-uploads")
    client = _s3_client()
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code not in {"404", "NoSuchBucket", "NotFound"}:
            raise
        client.create_bucket(Bucket=bucket)


def persist_upload(local_path: Path, content_type: str, prefix: str = "product-images") -> dict[str, str]:
    endpoint = os.getenv("S3_ENDPOINT_URL", "").strip()
    bucket = os.getenv("S3_BUCKET", "valuesee-uploads")
    if not endpoint:
        return {"backend": "local", "key": str(local_path.relative_to(Path.cwd())).replace("\\", "/")}

    client = _s3_client()
    ensure_bucket_exists()
    key = f"{prefix.strip('/')}/{local_path.name}"
    client.upload_file(str(local_path), bucket, key, ExtraArgs={"ContentType": content_type})
    return {"backend": "s3", "key": key}


def read_stored_object(backend: str, key: str) -> bytes | None:
    if backend == "local":
        path = (Path.cwd() / key).resolve()
        root = (Path.cwd() / "data" / "attachments").resolve()
        try:
            return path.read_bytes() if path.is_relative_to(root) and path.is_file() else None
        except OSError:
            return None
    if backend != "s3":
        return None
    from botocore.exceptions import BotoCoreError, ClientError

    client = _s3_client()
    try:
        response = client.get_object(Bucket=os.getenv("S3_BUCKET", "valuesee-uploads"), Key=key)
        body = response["Body"]
        try:
            return body.read()
        finally:
            body.close()
    except (BotoCoreError, ClientError, KeyError):
        return None


def delete_stored_object(backend: str, key: str) -> bool:
    try:
        if backend == "local":
            path = (Path.cwd() / key).resolve()
            root = (Path.cwd() / "data" / "attachments").resolve()
            if not path.is_relative_to(root):
                return False
            path.unlink(missing_ok=True)
            return True
        if backend != "s3":
            return False
        client = _s3_client()
        client.delete_object(Bucket=os.getenv("S3_BUCKET", "valuesee-uploads"), Key=key)
        return True
    except Exception:
        return False
