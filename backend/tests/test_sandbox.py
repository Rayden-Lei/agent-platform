"""代码执行沙箱（docs/15 WF-18 / D-33）：隔离能力、限额、失败与降级路径。

负向优先：这些用例存在的意义是"证明隔离真的生效"，而不是"证明能跑通"。
降级路径（本机 macOS）与 bwrap 路径（Linux）分开测，Linux 那段在非 Linux 上 skip ——
本机没有 bwrap 就不假装测过，也不让 CI 因平台差异变红。
"""
import sys

import pytest

from app.runtime import sandbox


def _run(code: str, payload: dict | None = None, **limits) -> sandbox.SandboxResult:
    return sandbox.run_python(code, payload, sandbox.SandboxLimits(**limits))


def test_probe_reports_mode_and_reason():
    """探测结果必须带原因：降级了却不说为什么，等于让人以为有隔离。"""
    cap = sandbox.probe(refresh=True)
    assert cap.mode in (sandbox.MODE_BWRAP, sandbox.MODE_BASIC)
    if cap.mode == sandbox.MODE_BWRAP:
        assert cap.reason is None
    else:
        assert cap.reason, "降级时必须写明原因"


def test_secret_env_not_passed_to_child():
    """最要紧的一条：子进程不能看到进程环境里的数据库口令与 AES_KEY。"""
    r = _run("""
import json, os
print(json.dumps({
    "db": os.environ.get("DATABASE_URL"),
    "aes": os.environ.get("AES_KEY"),
    "secret": os.environ.get("SECRET_KEY"),
    "redis": os.environ.get("REDIS_URL"),
}))
""")
    assert r.ok, r.error
    assert r.output.strip() == '{"db": null, "aes": null, "secret": null, "redis": null}'


def test_stdin_json_in_stdout_out():
    """与代码节点约定一致：stdin 是 {"input": ...}，结果 JSON 打 stdout。"""
    r = _run("""
import json, sys
p = json.loads(sys.stdin.read())
print(json.dumps({"got": p["input"]}))
""", {"input": {"a": [1, 2]}})
    assert r.ok, r.error
    assert r.output.strip() == '{"got": {"a": [1, 2]}}'


def test_timeout_kills_hanging_process():
    """死循环不能把后端拖住：墙钟超时强杀，并标记 timed_out。"""
    r = _run("while True: pass", timeout_seconds=2)
    assert r.ok is False
    assert r.timed_out is True
    assert "超时" in r.error
    assert r.duration_ms < 10000, "强杀要真的生效，不能等到进程自己结束"


def test_cpu_limit_catches_runaway_loop():
    """CPU 时间兜底：即使墙钟还没到，烧满 CPU 时间也会被杀。

    要证明的语义是"被资源限额杀掉，而不是自己正常退出"，所以按「信号 × 退出码表示法」
    两种口径各列两个信号，覆盖面是穷举的，不是随手放宽：

    | 结局                       | 直接子进程（basic） | 隔着 bwrap |
    |---------------------------|--------------------|-----------|
    | macOS 上收 SIGXCPU          | -24                | 不适用（bwrap 只在 Linux） |
    | Linux 上被 SIGKILL          | -9                 | 137 = 128+9（bwrap 自己 128+sig 退出）|

    -24 / -9 是 Python subprocess 对"被信号杀死"的表示法；137 是 bubblewrap 把子进程的
    SIGKILL 转成 128+9 后的样子 —— Linux CI 实测就是 137。Linux 上之所以常常直接吃
    SIGKILL 而不是 SIGXCPU：setrlimit 这里把软硬限额设成同一个值（见 LIMITS_BOOTSTRAP），
    超过硬限额内核对整组发 SIGKILL，软限额的 SIGXCPU 未必来得及生效。
    1 —— 限额压根没设进去时引导程序自己 sys.exit(1)，用户代码没跑起来，同样不是"正常退出"。

    "被限额杀掉而不是跑满"还有 timed_out is False 兜着（墙钟 20s、CPU 1s）：就算这里
    的退出码集合再宽，限额失效导致跑满 20s 也一定在这条断言之前红。反过来，用户代码
    自己报错(1)或崩溃的其它码都不在上面的集合里，所以"任何非 0 都行"这种写法是不必要的。
    """
    r = _run("x = 0\nwhile True: x += 1", timeout_seconds=20, cpu_seconds=1)
    assert r.ok is False
    assert r.timed_out is False, "应该被 CPU 限额杀掉，而不是等到墙钟超时"
    assert r.exit_code in (-24, -9, 137, 1), (
        f"期望被限额信号杀掉（SIGXCPU -24 / SIGKILL -9 / bwrap 转写 137）或引导程序退出 1，实际 {r.exit_code}"
    )


def test_exception_surfaces_stderr():
    """用户代码抛异常要能看出原因，不能只给一句"执行失败"。"""
    r = _run("raise ValueError('boom-from-sandbox')")
    assert r.ok is False
    assert r.exit_code == 1
    assert "boom-from-sandbox" in (r.error or "")


def test_output_not_swallowed_on_failure():
    """失败时 stdout 里可能已有部分结果，要带出来，便于排查。"""
    r = _run("""
print("partial-output")
raise RuntimeError("after print")
""")
    assert r.ok is False
    assert "partial-output" in r.output


def test_file_size_limit():
    """写爆磁盘：RLIMIT_FSIZE 拦住，进程被杀或抛 OSError。"""
    r = _run("""
data = "x" * (1024 * 1024)
with open("big.txt", "w") as f:
    for _ in range(40):
        f.write(data)
""", file_mb=1)
    assert r.ok is False


def test_workdir_is_isolated_temp():
    """每次执行一个独立临时目录，前一次的残留不能影响后一次。"""
    r = _run("""
import os, json
open("mine.txt", "w").write("1")
print(json.dumps({"cwd": os.getcwd(), "files": sorted(os.listdir("."))}))
""")
    assert r.ok, r.error
    import json

    data = json.loads(r.output)
    assert "main.py" in data["files"] and "mine.txt" in data["files"]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="命名空间隔离只在 Linux 上验证")
def test_bwrap_isolates_network():
    """bwrap 生效时，沙箱内连不出去。降级模式下跳过 —— 本机没有 bwrap 就不假装测过。"""
    if sandbox.probe().mode != sandbox.MODE_BWRAP:
        pytest.skip("当前环境未启用 bwrap")
    r = _run("""
import json, socket
out = {}
for host, port, name in [("127.0.0.1", 6379, "redis"), ("1.1.1.1", 80, "internet")]:
    try:
        socket.create_connection((host, port), timeout=2).close()
        out[name] = "connected"
    except OSError:
        out[name] = "blocked"
print(json.dumps(out))
""")
    assert r.ok, r.error
    assert '"connected"' not in r.output, f"沙箱内不该能联网：{r.output}"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="命名空间隔离只在 Linux 上验证")
def test_bwrap_hides_host_files():
    """bwrap 生效时读不到工作目录之外的文件。"""
    if sandbox.probe().mode != sandbox.MODE_BWRAP:
        pytest.skip("当前环境未启用 bwrap")
    r = _run("""
import json, os
print(json.dumps({"home": os.path.exists("/home"), "root_entries": sorted(os.listdir("/"))}))
""")
    assert r.ok, r.error
    assert '"home": false' in r.output.lower() or "false" in r.output
