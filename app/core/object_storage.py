from __future__ import annotations

import os
from pathlib import Path


def persist_upload(local_path: Path, content_type: str, prefix: str = "product-images") -> dict[str, str]:
    endpoint = os.getenv("S3_ENDPOINT_URL", "").strip()
    bucket = os.getenv("S3_BUCKET", "valuesee-uploads")
    if not endpoint:
        return {"backend": "local", "key": str(local_path.relative_to(Path.cwd())).replace("\\", "/")}

    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.getenv("S3_ACCESS_KEY"),
        aws_secret_access_key=os.getenv("S3_SECRET_KEY"),
        region_name=os.getenv("S3_REGION", "us-east-1"),
    )
    try:
        client.head_bucket(Bucket=bucket)
    except Exception:
        client.create_bucket(Bucket=bucket)
    key = f"{prefix.strip('/')}/{local_path.name}"
    client.upload_file(str(local_path), bucket, key, ExtraArgs={"ContentType": content_type})
    return {"backend": "s3", "key": key}


def create_download_url(backend: str, key: str, expires_seconds: int = 300) -> str | None:
    if backend == "local":
        path = (Path.cwd() / key).resolve()
        root = (Path.cwd() / "data" / "attachments").resolve()
        return str(path) if path.is_relative_to(root) and path.is_file() else None
    if backend != "s3":
        return None
    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=os.getenv("S3_ENDPOINT_URL", "").strip() or None,
        aws_access_key_id=os.getenv("S3_ACCESS_KEY"),
        aws_secret_access_key=os.getenv("S3_SECRET_KEY"),
        region_name=os.getenv("S3_REGION", "us-east-1"),
    )
    return client.generate_presigned_url("get_object", Params={"Bucket": os.getenv("S3_BUCKET", "valuesee-uploads"), "Key": key}, ExpiresIn=max(60, min(expires_seconds, 900)))


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
        import boto3

        client = boto3.client(
            "s3", endpoint_url=os.getenv("S3_ENDPOINT_URL", "").strip() or None,
            aws_access_key_id=os.getenv("S3_ACCESS_KEY"), aws_secret_access_key=os.getenv("S3_SECRET_KEY"),
            region_name=os.getenv("S3_REGION", "us-east-1"),
        )
        client.delete_object(Bucket=os.getenv("S3_BUCKET", "valuesee-uploads"), Key=key)
        return True
    except Exception:
        return False
