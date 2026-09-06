"""MinIO 对象存储客户端：文档文件的上传/下载。

懒加载单例；首次访问自动确保桶存在。secure=False 表示走 HTTP（内网部署场景），
若 MinIO 暴露在公网应改为 HTTPS。
"""
import io

import urllib3
from minio import Minio

from app.config import settings

_client = None


def get_minio() -> Minio:
    """获取全局 MinIO 客户端（懒加载单例）；桶不存在时自动创建。"""
    global _client
    if _client is None:
        # 显式超时与有限重试：默认的 urllib3 重试次数多、退避长，公网链路一抖就会卡住调用方几分钟
        # （2026-09-06 一次上传重试到 436 秒才失败）。连接超时短、读写超时按大文件留足，重试 2 次即放弃。
        http_client = urllib3.PoolManager(
            timeout=urllib3.Timeout(connect=5.0, read=settings.MINIO_TIMEOUT),
            retries=urllib3.Retry(total=2, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504]),
            maxsize=10,
        )
        _client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=False,
            http_client=http_client,
        )
        if not _client.bucket_exists(settings.MINIO_BUCKET):
            _client.make_bucket(settings.MINIO_BUCKET)
    return _client


def upload_file(object_name: str, data: bytes, content_type: str) -> None:
    """把内存字节流上传为对象。length 必须与 data 实际长度一致（此处直接用 len(data)）。"""
    client = get_minio()
    client.put_object(
        settings.MINIO_BUCKET,
        object_name,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )


def download_file(object_name: str, local_path: str) -> None:
    """下载对象到本地文件（文档处理流水线先下载到临时目录再解析）。"""
    client = get_minio()
    client.fget_object(settings.MINIO_BUCKET, object_name, local_path)
