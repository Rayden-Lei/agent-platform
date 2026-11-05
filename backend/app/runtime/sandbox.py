"""代码执行沙箱（docs/15 WF-18 / 决策 D-33）。

为什么要它：工作流的代码节点原来是裸 exec，放行完整 __builtins__，等于让有编辑权限的人
读到进程里的数据库口令与 AES_KEY（docs/01 NFR-002 已点名这是待收口项）。技能的 scripts/
也要靠同一套环境跑。

分两级，按环境能力自动选：
  bwrap  —— Linux 且 bubblewrap 可用：user / mount / net / pid / ipc / uts 命名空间全隔离，
            只读挂载系统目录，工作目录单独挂，/proc 是新的，网络直接断掉。
  basic  —— 其他情况（macOS 本机、没装 bwrap、容器里被 seccomp 拦、Ubuntu 24.04 没加 AppArmor
            profile）：清空环境变量 + rlimit + 超时。挡不住"读宿主文件"，挡得住"顺手读到密钥"
            与"打死进程/写爆磁盘"。

为什么不用 setuid bwrap 或全局关掉 userns 限制：前者等于给沙箱工具 root 权限，后者削弱整机安全。
探测失败就降级，并在 /system/status 里明确写出来 —— 静默降级比不做还危险，因为没人知道隔离没了。

**macOS 上 RLIMIT_AS 不可用**：实测在 macOS 给子进程设 RLIMIT_AS 会让 preexec_fn 直接抛异常、
子进程起不来。所以内存上限只在 Linux 生效，macOS 的降级路径挡不住"死循环吃内存"。这不是遗漏，
是平台限制，写在 probe() 返回的 reason 里，也写在 docs/08。
"""
import json
import logging
import os
import resource
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass

logger = logging.getLogger(__name__)

MODE_BWRAP = "bwrap"
MODE_BASIC = "basic"

# 沙箱里能用的环境变量：只给 PATH 与语言相关的几项，其余一律不传（数据库口令、AES_KEY 都在进程环境里）
PASSTHROUGH_ENV = ("PATH", "LANG", "LC_ALL", "TZ")
DEFAULT_PATH = "/usr/local/bin:/usr/bin:/bin"

# 默认限额：一次代码节点/技能脚本是"算点东西"，不是跑训练任务
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MEMORY_MB = 256
DEFAULT_CPU_SECONDS = 30
DEFAULT_FILE_MB = 16
DEFAULT_NPROC = 64


@dataclass(frozen=True)
class SandboxLimits:
    """一次执行的上限。timeout 是墙钟（进程整体存活时间），cpu 是 CPU 时间（死循环也能被 CPU 时间兜住）。"""

    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    memory_mb: int = DEFAULT_MEMORY_MB
    cpu_seconds: int = DEFAULT_CPU_SECONDS
    file_mb: int = DEFAULT_FILE_MB
    nproc: int = DEFAULT_NPROC


@dataclass(frozen=True)
class SandboxResult:
    """一次执行的结果。ok 为假时 error 是给调用方看的说明，stderr 是程序自己的输出（可能为空）。"""

    ok: bool
    output: str
    error: str | None
    stderr: str
    exit_code: int | None
    duration_ms: int
    mode: str
    timed_out: bool = False


# ---------- 能力探测 ----------

@dataclass(frozen=True)
class SandboxCapability:
    """当前环境的沙箱能力。probe() 的结果缓存一次，避免每次执行都去试一遍 bwrap。"""

    mode: str
    reason: str | None  # 降级原因；mode=bwrap 时为 None
    detail: dict


def _bwrap_works(bwrap: str) -> tuple[bool, str | None]:
    """真的跑一次 bwrap 建命名空间，而不是只看文件在不在。

    必须实测：Ubuntu 24.04 起 kernel.apparmor_restrict_unprivileged_userns=1 会拦住未标记 profile 的
    程序创建 user namespace，容器里默认 seccomp 也会拦。这两种情况下 bwrap 装着但用不了，
    只看 which 会得到一个"以为有隔离、其实每次都失败"的沙箱。
    """
    try:
        # 用与真实执行同一套参数探测：探测通过但执行参数不同，等于测了个别的东西。
        # 工作目录用一次性临时目录，不把宿主的 /tmp 挂进探测沙箱。
        with tempfile.TemporaryDirectory(prefix="sbx-probe-") as probe_dir:
            r = subprocess.run(
                _bwrap_argv(bwrap, probe_dir, None) + ["--", "/bin/true"],
                capture_output=True, text=True, timeout=10,
            )
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"执行 bwrap 失败：{e}"
    if r.returncode == 0:
        return True, None
    message = (r.stderr or r.stdout or "").strip().splitlines()
    return False, message[0][:300] if message else f"bwrap 退出码 {r.returncode}"


def probe(refresh: bool = False) -> SandboxCapability:
    """当前环境的沙箱能力。结果缓存；refresh=True 时重新探测（改完服务器配置不用重启后端）。"""
    global _capability
    if _capability is not None and not refresh:
        return _capability
    if not sys.platform.startswith("linux"):
        _capability = SandboxCapability(MODE_BASIC, f"当前平台 {sys.platform} 不支持 bwrap，降级为清空环境 + 限额", {"platform": sys.platform})
        return _capability
    bwrap = shutil.which("bwrap")
    if bwrap is None:
        _capability = SandboxCapability(MODE_BASIC, "未安装 bubblewrap，降级为清空环境 + 限额", {"bwrap": None})
        return _capability
    ok, reason = _bwrap_works(bwrap)
    if not ok:
        _capability = SandboxCapability(
            MODE_BASIC,
            f"bubblewrap 不可用（{reason}），降级为清空环境 + 限额。Ubuntu 24.04+ 需要给 bwrap 加 AppArmor profile，见 docs/08",
            {"bwrap": bwrap, "probe_error": reason},
        )
        return _capability
    _capability = SandboxCapability(MODE_BWRAP, None, {"bwrap": bwrap})
    return _capability


_capability: SandboxCapability | None = None


def status() -> dict:
    """给 /system/status 用：当前模式与降级原因。"""
    cap = probe()
    return {"mode": cap.mode, "degraded": cap.mode != MODE_BWRAP, "reason": cap.reason, "detail": cap.detail}


# ---------- 执行 ----------

def _child_env() -> dict:
    """子进程环境：只保留 PASSTHROUGH_ENV 里显式列出的项，其余全部丢掉。

    这是降级路径最要紧的一步 —— 进程环境里有 DATABASE_URL、AES_KEY、SECRET_KEY，
    不清就等于把平台的根凭据交给一段模型生成的代码。
    """
    env = {k: os.environ[k] for k in PASSTHROUGH_ENV if k in os.environ}
    env.setdefault("PATH", DEFAULT_PATH)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _limits(limits: SandboxLimits) -> list[tuple[int, int]]:
    """要设的 rlimit 列表。RLIMIT_AS 在 macOS 上不可用（设了会让 preexec 抛异常），按平台过滤。"""
    items = [
        (resource.RLIMIT_CPU, limits.cpu_seconds),
        (resource.RLIMIT_FSIZE, limits.file_mb * 1024 * 1024),
        (resource.RLIMIT_NPROC, limits.nproc),
    ]
    if sys.platform.startswith("linux"):
        items.append((resource.RLIMIT_AS, limits.memory_mb * 1024 * 1024))
    return items


# 限额由子进程自己设，**不用 preexec_fn**。
# Python 文档明确写着 preexec_fn 在多线程进程里不安全（可能在 fork 与 exec 之间死锁），
# 而后端就是多线程的（uvicorn 线程池）。所以改成：启动一个引导程序，它先设 rlimit、
# 再执行用户的脚本。进程组用 Popen(start_new_session=True) 建立，那是在 C 层做的，没有这个问题。
LIMITS_BOOTSTRAP = """
import resource, sys

for res, value in {limits!r}:
    try:
        resource.setrlimit(res, (value, value))
    except (ValueError, OSError) as e:
        sys.stderr.write("设置限额失败 %s=%s：%s\\n" % (res, value, e))
        sys.exit(1)

_script = sys.argv[1]
with open(_script, encoding="utf-8") as f:
    _code = f.read()
sys.argv = [_script]
exec(compile(_code, _script, "exec"), {{"__name__": "__main__", "__file__": _script}})
"""


# 系统目录里的这几项在现代发行版上都是符号链接（Ubuntu 24.04：/bin -> usr/bin、/lib -> usr/lib）。
# 对符号链接做 --ro-bind 会静默得到一个空目录，然后 execvp 报 "No such file or directory" ——
# 2026-11-05 在阿里云 Ubuntu 24.04 上实测踩过：bind /bin 之后连 /bin/true 都找不到。
# 正确做法是 --symlink 重建同样的链接（Flatpak 的做法），已挂 /usr 的前提下这些路径自然可用。
SYSTEM_SYMLINKS = (("/bin", "usr/bin"), ("/sbin", "usr/sbin"), ("/lib", "usr/lib"), ("/lib64", "usr/lib64"))


def _bwrap_argv(bwrap: str, workdir: str, interpreter: str | None) -> list[str]:
    """bwrap 参数。要点：
    - --unshare-all 一次把 user/mount/net/pid/ipc/uts/cgroup 全隔开，网络直接断掉（技能脚本不该联网）
    - --die-with-parent：父进程被强杀时沙箱内进程一起走，不留孤儿
    - --clearenv：不继承宿主环境（再用 --setenv 显式传需要的几项）
    - 系统目录只读挂载；工作目录单独挂到 /work，可写
    - 解释器所在目录也要挂：生产是 /app/.venv/bin/python，不在 /usr 下，漏了会报 No such file
    """
    argv = [
        bwrap, "--unshare-all", "--die-with-parent", "--clearenv",
        "--dev", "/dev", "--proc", "/proc",
        "--ro-bind", "/usr", "/usr",
        "--bind", workdir, "/work", "--chdir", "/work",
        "--tmpfs", "/tmp",
    ]
    # /bin /sbin /lib /lib64：宿主上是符号链接就重建链接，是真实目录才 bind
    for path, target in SYSTEM_SYMLINKS:
        if os.path.islink(path):
            argv += ["--symlink", target, path]
        elif os.path.isdir(path):
            argv += ["--ro-bind", path, path]
    # /etc 只挑程序真正会读的几项，不整目录挂（里面有 shadow、ssh 私钥、数据库口令配置）
    for path in ("/etc/ssl", "/etc/ca-certificates", "/etc/alternatives", "/etc/ld.so.cache", "/etc/localtime"):
        if os.path.exists(path):
            argv += ["--ro-bind", path, path]
    # venv 的解释器不在 /usr 下时补挂虚拟环境根目录（如 /app/.venv）。
    # 用 abspath 而不是 realpath：venv 里的 python 是指向系统解释器的符号链接，
    # realpath 会把它解析回 /usr/bin/python3.x，于是这段判断认为"在 /usr 下、不用挂"，
    # 结果沙箱里找不到 venv 的 python 与 site-packages。2026-11-05 在云服务器实测踩到。
    if interpreter:
        root = os.path.dirname(os.path.dirname(os.path.abspath(interpreter)))
        if root and os.path.isdir(root) and not root.startswith(("/usr", "/bin", "/lib", "/sbin")):
            argv += ["--ro-bind", root, root]
    env = _child_env()
    for key, value in env.items():
        argv += ["--setenv", key, value]
    return argv


def _kill_group(proc: subprocess.Popen) -> None:
    """整组杀掉：子进程用 setsid 起了新会话，杀它自己不够，fork 出来的孙进程还活着。"""
    try:
        os.killpg(os.getpgid(proc.pid), 9)
    except (ProcessLookupError, PermissionError):
        proc.kill()


def run_python(code: str, stdin_payload: dict | None = None, limits: SandboxLimits | None = None) -> SandboxResult:
    """在沙箱里跑一段 Python：code 从 stdin 读 JSON、把结果 JSON 打到 stdout。

    约定（调用方与模板都照这个来）：stdin 是 {"input": ...}，程序把结果 print 成 JSON 到 stdout。
    返回值里的 output 是 stdout 原文，由调用方决定要不要按 JSON 解析 —— 沙箱不替它猜格式。
    """
    import time

    limits = limits or SandboxLimits()
    cap = probe()
    started = time.perf_counter()
    payload = json.dumps(stdin_payload or {}, ensure_ascii=False)
    with tempfile.TemporaryDirectory(prefix="sbx-") as workdir:
        script = os.path.join(workdir, "main.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write(code)
        interpreter = sys.executable
        bootstrap = LIMITS_BOOTSTRAP.format(limits=_limits(limits))
        if cap.mode == MODE_BWRAP:
            argv = _bwrap_argv(cap.detail["bwrap"], workdir, interpreter) + ["--", interpreter, "-c", bootstrap, "/work/main.py"]
        else:
            argv = [interpreter, "-c", bootstrap, script]
        try:
            proc = subprocess.Popen(
                argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, cwd=workdir, env=_child_env(), start_new_session=True,
            )
        except (OSError, subprocess.SubprocessError) as e:
            logger.warning("沙箱启动失败 mode=%s：%s", cap.mode, e)
            return SandboxResult(False, "", f"沙箱启动失败：{e}", "", None, _elapsed(started), cap.mode)
        timed_out = False
        try:
            stdout, stderr = proc.communicate(payload, timeout=limits.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_group(proc)
            stdout, stderr = proc.communicate()
    duration = _elapsed(started)
    if timed_out:
        logger.warning("沙箱执行超时 mode=%s 限制=%ss", cap.mode, limits.timeout_seconds)
        return SandboxResult(False, "", f"执行超时（超过 {limits.timeout_seconds} 秒）", (stderr or "")[:4000], proc.returncode, duration, cap.mode, True)
    if proc.returncode != 0:
        # 退出码非 0 不等于失败：Python 里抛异常才是常见原因，把 stderr 原样带出去让调用方/模型自己看
        tail = (stderr or "").strip().splitlines()
        message = tail[-1][:300] if tail else f"退出码 {proc.returncode}"
        return SandboxResult(False, stdout or "", message, (stderr or "")[:4000], proc.returncode, duration, cap.mode)
    return SandboxResult(True, stdout or "", None, (stderr or "")[:4000], proc.returncode, duration, cap.mode)


def _elapsed(started: float) -> int:
    import time

    return int((time.perf_counter() - started) * 1000)
