"""SKILL.md 导入（docs/17 §4.5）：把 Agent Skills 开放标准的 SKILL.md 解析成本平台的技能字段。

格式（https://agentskills.io/specification）：
    ---
    name: pdf-processing
    description: 提取 PDF 文本、填表、合并文件。处理 PDF 或用户提到表单时使用。
    license: Apache-2.0
    compatibility: 需要 Python 3.12+
    allowed-tools: Bash(git:*) Read
    metadata:
      author: example-org
      version: "1.0"
    ---
    # 正文 Markdown …

本模块只做**解析与规范化**，不写库：解析结果回给前端填进编辑弹窗，使用者确认后再走正常的
POST /skills 保存。这样导入与手填走同一条校验路径（name 格式、description 必填、正文 64KB），
不会出现"导入能绕过校验"的第二套入口。

不引 PyYAML：frontmatter 实际用到的只有「标量键值」与「一层嵌套 map」两种结构，
为它装一个解析器不值得。真遇到复杂 YAML（多行折叠、锚点、列表）按不支持处理并明确报错，
不猜、不静默丢字段。
"""
import re

# frontmatter 必须从第一行开始（前面允许一个 UTF-8 BOM 与空行），以 --- 包起来
_FRONTMATTER = re.compile(r"^\ufeff?\s*---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)
# 顶层键：不缩进、形如 key: value 或 key:
_TOP_KEY = re.compile(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$")
# 嵌套键：缩进两个及以上空格
_NESTED_KEY = re.compile(r"^\s+([A-Za-z0-9_-]+)\s*:\s*(.*)$")
# 本平台存不下的 frontmatter 字段：解析出来放进 meta 原样保留，不丢信息
META_FIELDS = ("license", "compatibility", "allowed-tools", "metadata")


class SkillImportError(ValueError):
    """SKILL.md 格式不合法。message 直接回给使用者，要能看懂哪里不对、怎么改。"""


def _unquote(value: str) -> str:
    """去掉成对的引号。YAML 的单双引号都能包字符串，值里本身带冒号时作者一定会加引号。"""
    v = value.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    return v


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """拆成 (frontmatter 字典, 正文 Markdown)。没有 frontmatter 时抛错 —— 那不是合法的 SKILL.md。"""
    match = _FRONTMATTER.match(text)
    if match is None:
        raise SkillImportError("没有找到 frontmatter：SKILL.md 必须以三横线 --- 开头，先写 name 与 description，再写三横线结束")
    body = text[match.end():]
    # 值只有两种形态：标量（str）与一层嵌套 map（如 metadata: {author: x}），后者原样进 fields
    fields: dict[str, str | dict[str, str]] = {}
    nested: dict[str, dict[str, str]] = {}
    current: str | None = None
    for raw in match.group(1).splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        top = _TOP_KEY.match(raw)
        if top:
            key, value = top.group(1), top.group(2)
            current = key if not value.strip() else None
            if value.strip():
                fields[key] = _unquote(value)
            else:
                nested[key] = {}
            continue
        child = _NESTED_KEY.match(raw)
        if child and current:
            nested[current][child.group(1)] = _unquote(child.group(2))
            continue
        # 多行折叠、列表、锚点等结构这里不支持：明确报错，不静默丢掉作者写的内容
        raise SkillImportError(f"frontmatter 里有本平台暂不支持的结构：{raw.strip()[:60]}（只支持 key: value 与一层嵌套）")
    for key, children in nested.items():
        # 「key:」后面没有缩进行时落一个空 map（YAML 的空映射语义）；有缩进行时放这一层 map。
        # 用 setdefault 而不是直接赋值：同一个键先写成标量、后面只写了一行空的「key:」时，
        # 作者写的标量值才是他想要的内容，不能被空 map 顶掉。
        if children:
            fields[key] = children
        else:
            fields.setdefault(key, children)
    return fields, body.strip("\n")


def to_skill(frontmatter: dict, body: str) -> dict:
    """frontmatter + 正文 → 技能字段（不含 id / version 这些由库生成的）。

    name / description 缺失直接报错而不是给默认值：Agent Skills 规范里两者都是必填，
    编一个 name 会让模型调 load_skill 时找不到它，给个空 description 等于技能永远不会被加载。
    """
    name = str(frontmatter.get("name") or "").strip()
    description = str(frontmatter.get("description") or "").strip()
    if not name:
        raise SkillImportError("frontmatter 缺少 name")
    if not description:
        raise SkillImportError("frontmatter 缺少 description（它决定模型会不会用这个技能，不能为空）")
    if not body.strip():
        raise SkillImportError("正文为空：frontmatter 之后要写技能的操作步骤")
    meta = {k: frontmatter[k] for k in META_FIELDS if k in frontmatter}
    # metadata 是唯一的一层嵌套 map；作者把它写成标量（metadata: x）属于不规范用法，按「没写」处理，
    # 后面取值时才不会在非 dict 上 .get 崩掉
    nested_meta = meta.get("metadata")
    if isinstance(nested_meta, dict):
        nested_meta = {str(k): str(v) for k, v in nested_meta.items()}
        meta["metadata"] = nested_meta
    else:
        nested_meta = {}
    return {
        "name": name,
        "display_name": str(nested_meta.get("title") or name)[:128],
        "description": description[:1024],
        "content": body,
        # always_on 默认关：导入的技能大多是可查可不查的长手册，常驻会把上下文占满，
        # 让使用者在编辑弹窗里自己决定要不要常驻
        "always_on": False,
        "is_enabled": True,
        "resources": [],
        # 原样保留 license / compatibility / allowed-tools / metadata，前端可以展示，不丢作者写的信息
        "meta": meta,
    }


def parse_skill_md(text: str) -> dict:
    """SKILL.md 全文 → 技能字段。接口层与用例都走这一个入口。"""
    frontmatter, body = parse_frontmatter(text)
    return to_skill(frontmatter, body)
