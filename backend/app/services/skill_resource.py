"""技能资源与脚本（docs/17 §4.5，P2.6）：资源进对象存储，脚本走沙箱执行。

技能的 resources 从"只存文本"扩展成两类：
  {"name": "extract.py", "type": "text", "content": "..."}        内联文本（小片段，直接进库）
  {"name": "extract.py", "type": "file", "object": "skills/3/extract.py", "size": 1234}   文件型（进 MinIO）

为什么分两类而不是全进 MinIO：几行的配置片段塞进 MinIO 只会让"打开技能就看到内容"变成多一次网络往返；
反过来几十 KB 的脚本塞进 jsonb 会让技能行膨胀、列表查询被拖慢。按大小与用途分开更实在。

**脚本路径必须白名单**：load_skill 只读绑定技能的正文，run_skill_script 也只能跑**该技能自己的**
resources 里登记过的脚本。路径来自模型生成的参数，不做白名单就等于给了它读任意对象的入口。

首版只支持 Python（沙箱用 python 跑），扩展名白名单限定 .py；其它语言等真有需求再加，
现在先不给一个"能跑 shell 但沙箱没按 shell 加固"的口子。
"""
import posixpath

from sqlalchemy.orm import Session

from app.core.exceptions import BizError
from app.db.models import Skill
from app.rag import minio_client
from app.runtime import sandbox

# 单个资源上限：脚本是"算点东西"的小程序，不是数据文件
RESOURCE_MAX_BYTES = 512 * 1024
# 单次执行脚本时从对象存储读出来的上限（防一个超大对象把内存吃光）
SCRIPT_READ_MAX_BYTES = 1024 * 1024
# 首版只跑 Python：沙箱按 python 起进程，别的语言需要另一套加固
SCRIPT_SUFFIXES = (".py",)
OBJECT_PREFIX = "skills"


def object_name(skill_id: int, name: str) -> str:
    """资源在桶里的对象名。带上技能 id 前缀，删技能时按前缀清、不同技能的同名脚本互不覆盖。"""
    return f"{OBJECT_PREFIX}/{skill_id}/{name}"


def _safe_resource_name(name: str) -> str:
    """资源名只允许"文件名 + 可选的单层目录"，不允许 .. / 绝对路径 / 反斜杠。

    这不是洁癖：资源名会被拼进对象名，也会被 run_skill_script 当路径参数用。
    允许 ../ 就等于让模型能读到别的技能的资源。
    """
    cleaned = (name or "").strip()
    if not cleaned or cleaned.startswith(("/", "\\")) or ".." in cleaned or "\\" in cleaned:
        raise BizError(400, f"资源名不合法：{name!r}")
    normalized = posixpath.normpath(cleaned)
    if normalized != cleaned or normalized.startswith(".."):
        raise BizError(400, f"资源名不合法：{name!r}")
    return cleaned


def store_file(skill_id: int, name: str, data: bytes, content_type: str = "text/plain") -> dict:
    """把资源写进 MinIO，返回要存进 skills.resources 的那一条。"""
    if len(data) > RESOURCE_MAX_BYTES:
        raise BizError(400, f"单个资源最多 {RESOURCE_MAX_BYTES // 1024}KB，{name} 有 {len(data) / 1024:.1f}KB")
    safe = _safe_resource_name(name)
    obj = object_name(skill_id, safe)
    minio_client.upload_file(obj, data, content_type)
    return {"name": safe, "type": "file", "object": obj, "size": len(data)}


def drop_file(object_name_: str) -> None:
    """删资源对象。删技能或替换资源时调用；对象不存在也不报错。"""
    minio_client.remove_object(object_name_)


def drop_all(skill_id: int, resources: list) -> None:
    """删技能时清掉它名下的文件型资源。文本型的不涉及对象存储，跳过。"""
    for r in resources or []:
        obj = r.get("object")
        if obj:
            drop_file(obj)


def script_of(skill: Skill, path: str) -> dict:
    """在**该技能自己的** resources 里找脚本。找不到 → 404「脚本不存在」。

    不做"按路径读任意对象"的兜底：模型传什么都能读到，等于把整个桶变成它的文件系统。
    """
    safe = _safe_resource_name(path)
    for r in skill.resources or []:
        if r.get("name") != safe:
            continue
        if not safe.endswith(SCRIPT_SUFFIXES):
            raise BizError(400, f"首版只支持执行 {' / '.join(SCRIPT_SUFFIXES)} 脚本，{safe} 不是")
        if r.get("type") == "file":
            return {"name": safe, "object": r["object"], "inline": None}
        return {"name": safe, "object": None, "inline": r.get("content") or ""}
    raise BizError(404, f"脚本不存在：{safe}")


def run_script(skill: Skill, path: str, payload: dict | None = None, limits: sandbox.SandboxLimits | None = None) -> sandbox.SandboxResult:
    """把技能里的一个脚本交给沙箱执行，stdin 收 {"input": ...}，stdout 出结果。

    脚本内容在**执行时**从库里或对象存储取，不在装配时缓存：技能页改完脚本立刻生效，
    与技能正文同一口径（技能不进发布快照）。
    """
    found = script_of(skill, path)
    if found["inline"] is not None:
        code = found["inline"]
    else:
        try:
            code = minio_client.read_bytes(found["object"], limit=SCRIPT_READ_MAX_BYTES).decode("utf-8")
        except ValueError as e:
            raise BizError(400, str(e)) from e
        except UnicodeDecodeError as e:
            raise BizError(400, f"脚本不是 UTF-8 文本：{found['name']}") from e
    return sandbox.run_python(code, payload, limits)


def list_resources(db: Session, skill_id: int) -> list[dict]:
    """技能的资源清单：文件型的补上实际大小，对象被外部删掉时标 missing。

    只发**一次** list_objects 取回该技能前缀下所有对象，再在内存里装配 ——
    逐个 stat_object 是循环里发 IO，20 个资源就是 20 次往返（docs/09）。
    """
    skill = db.get(Skill, skill_id)
    if skill is None:
        raise BizError(404, "技能不存在")
    entries = skill.resources or []
    # 没有文件型资源时不必访问对象存储（纯文本资源的技能页不产生一次网络往返）
    objects = (
        minio_client.list_objects(f"{OBJECT_PREFIX}/{skill_id}/")
        if any(r.get("type") == "file" and r.get("object") for r in entries)
        else {}
    )
    out = []
    for r in entries:
        item = dict(r)
        if r.get("type") == "file" and r.get("object"):
            size = objects.get(r["object"])
            item["size"] = size
            item["missing"] = size is None
        else:
            item["size"] = len((r.get("content") or "").encode("utf-8"))
            item["missing"] = False
        out.append(item)
    return out
