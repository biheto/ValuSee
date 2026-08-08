from __future__ import annotations

import os
from pathlib import Path


def persist_upload(local_path: Path, content_type: str) -> dict[str, str]:
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
    key = f"product-images/{local_path.name}"
    client.upload_file(str(local_path), bucket, key, ExtraArgs={"ContentType": content_type})
    return {"backend": "s3", "key": key}
