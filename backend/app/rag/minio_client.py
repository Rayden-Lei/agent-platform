import io

from minio import Minio

from app.config import settings

_client = None


def get_minio() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=False,
        )
        if not _client.bucket_exists(settings.MINIO_BUCKET):
            _client.make_bucket(settings.MINIO_BUCKET)
    return _client


def upload_file(object_name: str, data: bytes, content_type: str) -> None:
    client = get_minio()
    client.put_object(
        settings.MINIO_BUCKET,
        object_name,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )


def download_file(object_name: str, local_path: str) -> None:
    client = get_minio()
    client.fget_object(settings.MINIO_BUCKET, object_name, local_path)
