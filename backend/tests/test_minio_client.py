"""对象存储客户端（rag/minio_client.py）本身。

为什么单独测：其余用例（test_skill_resource 等）都是把 minio_client 的**函数**整体打桩，
测到的是"调用方有没有按约定调"，而这里面的懒加载单例、桶自动创建、分块读与超限中断、
S3Error 翻译一行都没被执行过。它们出错的后果是上传/下载/删技能直接 500 或内存被撑爆。

不连真实 MinIO：把模块里的 Minio 类换成内存假实现，只验控制流与边界。
"""
from __future__ import annotations

import pytest
from minio.error import S3Error

from app.config import settings
from app.rag import minio_client


class _FakeResponse:
    """get_object 返回的流：按 64KB 分块产出，并记录是否被关闭。"""

    def __init__(self, data: bytes):
        self._data = data
        self.closed = False
        self.released = False

    def stream(self, chunk_size: int):
        for i in range(0, len(self._data), chunk_size):
            yield self._data[i:i + chunk_size]

    def close(self):
        self.closed = True

    def release_conn(self):
        self.released = True


class _FakeMinio:
    """内存版 Minio：只实现被测代码用到的几个方法。"""

    def __init__(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs
        self.objects: dict[str, bytes] = {}
        self.buckets: set[str] = set()
        self.made: list[str] = []
        self.removed: list[str] = []
        self.fail_stat: S3Error | None = None
        self.last_response: _FakeResponse | None = None
        # 让用例能断言"桶已存在时不该再建"
        self.bucket_exists_result = False

    def bucket_exists(self, name):
        return self.bucket_exists_result or name in self.buckets

    def make_bucket(self, name):
        self.buckets.add(name)
        self.made.append(name)

    def put_object(self, bucket, name, data, length=None, content_type=None):
        raw = data.read() if hasattr(data, "read") else data
        assert len(raw) == length, f"length={length} 与实际 {len(raw)} 不一致"
        self.objects[name] = raw

    def fput_object(self, bucket, name, path, content_type=None):
        with open(path, "rb") as f:
            self.objects[name] = f.read()

    def fget_object(self, bucket, name, path):
        with open(path, "wb") as f:
            f.write(self.objects[name])

    def get_object(self, bucket, name):
        self.last_response = _FakeResponse(self.objects[name])
        return self.last_response

    def remove_object(self, bucket, name):
        self.removed.append(name)
        self.objects.pop(name, None)

    def list_objects(self, bucket, prefix="", recursive=False):
        class _Obj:
            def __init__(self, object_name, size):
                self.object_name, self.size = object_name, size

        for key, value in self.objects.items():
            if key.startswith(prefix):
                yield _Obj(key, len(value))
        # 目录条目与缺 Size 的响应在 SDK 里都是 None：返回类型承诺 {名字: 字节数}，
        # 这类条目必须被过滤掉，不能塞 None 进去
        yield _Obj(None, 1)
        yield _Obj("prefix/nosize", None)

    def stat_object(self, bucket, name):
        if self.fail_stat is not None:
            raise self.fail_stat
        if name not in self.objects:
            raise _s3_error("NoSuchKey", name)

        class _Stat:
            size = len(self.objects[name])
            content_type = "text/plain"

        return _Stat()


def _s3_error(code: str, name: str) -> S3Error:
    """S3Error 的第一个位置参数是 response（不是 code），所以这里传 None 占位。"""
    return S3Error(None, code, f"msg for {name}", name, "req", "host", "GET")


@pytest.fixture
def fake(monkeypatch):
    """替换 Minio 类并清掉单例：每个用例拿到一个干净的内存桶。"""
    instance = _FakeMinio()

    def _factory(*args, **kwargs):
        # 把真实传参记到实例上：单例与超时/重试配置都是"有没有真的传下去"才作数
        instance.args, instance.kwargs = args, kwargs
        return instance

    monkeypatch.setattr(minio_client, "Minio", _factory)
    monkeypatch.setattr(minio_client, "_client", None)
    yield instance
    monkeypatch.setattr(minio_client, "_client", None)


# --------------------------------------------------------------------------- 单例与建桶

def test_get_minio_is_lazy_singleton(fake):
    """懒加载单例：多次取用只建一个客户端（每次新建都会重新建连接池）。"""
    first = minio_client.get_minio()
    second = minio_client.get_minio()
    assert first is second is fake


def test_bucket_is_created_once_when_absent(fake):
    """桶不存在时自动创建 —— 否则首次部署的第一次上传就 500。"""
    minio_client.get_minio()
    assert fake.made == [settings.MINIO_BUCKET]
    # 第二次取用不会重复建桶（单例已存在）
    minio_client.get_minio()
    assert fake.made == [settings.MINIO_BUCKET]


def test_bucket_not_recreated_when_present(fake):
    fake.bucket_exists_result = True
    minio_client.get_minio()
    assert fake.made == []


def test_client_uses_configured_timeouts(fake):
    """超时与重试必须真的传下去：默认的 urllib3 重试退避会把调用方卡几分钟。"""
    minio_client.get_minio()
    http_client = fake.kwargs["http_client"]
    assert http_client.connection_pool_kw["timeout"].connect_timeout == 5.0
    assert http_client.connection_pool_kw["retries"].total == 2
    assert fake.kwargs["secure"] is False


# --------------------------------------------------------------------------- 读写

def test_upload_file_roundtrip(fake):
    minio_client.upload_file("a/b.txt", b"hello", "text/plain")
    assert fake.objects["a/b.txt"] == b"hello"


def test_upload_file_passes_exact_length(fake):
    """put_object 的 length 必须等于实际长度：不等时 MinIO 会挂住连接而不是报错。
    假实现里对这个等式做了断言，所以这里只要传对就能通过。"""
    minio_client.upload_file("a/b.txt", b"hello", "text/plain")
    assert fake.objects["a/b.txt"] == b"hello"


def test_upload_path_streams_from_disk(fake, tmp_path):
    src = tmp_path / "x.txt"
    src.write_bytes(b"from disk")
    minio_client.upload_path("a/x.txt", str(src), len(b"from disk"), "text/plain")
    assert fake.objects["a/x.txt"] == b"from disk"


def test_download_file_writes_to_disk(fake, tmp_path):
    fake.objects["a/y.txt"] = b"payload"
    dst = tmp_path / "out.txt"
    minio_client.download_file("a/y.txt", str(dst))
    assert dst.read_bytes() == b"payload"


def test_read_bytes_returns_whole_object(fake):
    fake.objects["a/z.txt"] = b"0123456789"
    assert minio_client.read_bytes("a/z.txt") == b"0123456789"


def test_read_bytes_stops_at_limit(fake):
    """超限要在读到一半时就中断：不能先整块读进内存再判断（一个 200MB 对象能拖死后端）。"""
    fake.objects["a/big.bin"] = b"x" * (200 * 1024)
    with pytest.raises(ValueError) as ei:
        minio_client.read_bytes("a/big.bin", limit=64 * 1024)
    assert "超过上限" in str(ei.value)


def test_read_bytes_closes_response_even_on_limit(fake):
    """超限抛错也必须把连接还回去，否则连接池会被慢慢耗光。"""
    fake.objects["a/big.bin"] = b"x" * (200 * 1024)
    with pytest.raises(ValueError):
        minio_client.read_bytes("a/big.bin", limit=1024)
    assert fake.last_response.closed and fake.last_response.released


def test_read_bytes_closes_response_on_success(fake):
    fake.objects["a/ok.txt"] = b"ok"
    minio_client.read_bytes("a/ok.txt")
    assert fake.last_response.closed and fake.last_response.released


# --------------------------------------------------------------------------- 列举与元信息

def test_list_objects_filters_none_entries(fake):
    """SDK 里 object_name / size 都是 Optional：目录条目与缺 Size 的响应要被过滤掉，
    否则清单里会出现 None 键，或 None 值被当成"对象不存在"。"""
    fake.objects["skills/1/a.py"] = b"aaa"
    fake.objects["skills/1/b.py"] = b"bb"
    fake.objects["other/c.py"] = b"c"
    got = minio_client.list_objects("skills/1/")
    assert got == {"skills/1/a.py": 3, "skills/1/b.py": 2}


def test_remove_object_is_idempotent(fake):
    """删不存在的对象不报错（MinIO 本身幂等）：删技能时不必先查存在性。"""
    minio_client.remove_object("never/existed.txt")
    assert fake.removed == ["never/existed.txt"]


def test_stat_object_returns_size_and_type(fake):
    fake.objects["a/s.txt"] = b"12345"
    assert minio_client.stat_object("a/s.txt") == {"size": 5, "content_type": "text/plain"}


def test_stat_object_missing_returns_none(fake):
    """对象不存在返回 None 而不是抛错：列表页要能显示"这条资源丢了"。"""
    assert minio_client.stat_object("a/none.txt") is None


def test_stat_object_reraises_other_s3_errors(fake):
    """只有"不存在"翻译成 None，其他 S3 错误必须往上抛 —— 把权限错误也吞成 None
    会让"资源丢了"和"没权限看"混在一起，排查方向全错。"""
    fake.fail_stat = _s3_error("AccessDenied", "a/s.txt")
    with pytest.raises(S3Error):
        minio_client.stat_object("a/s.txt")
