"""迁移：把能力型内置工具写进 tools 表，让它们在工具页可见、可挂到智能体上。

改什么：向 tools 表插入 8 条 type='builtin' 的记录（text_stats / random_int /
  random_choice / base64_encode / base64_decode / json_query / http_request / web_search）。
为什么：内置工具原本是代码里硬编码的 current_time + calculator，每个智能体无条件挂上；
  新增的这批是"能力型"的，按需挂载才合理（不是每个智能体都需要联网搜索）。
  但它们必须在 tools 表里有行，否则工具页列不出来、智能体也没法勾选。
影响：只插入新行，不改存量。已存在同名工具则跳过（按 name 幂等）。
执行后必做：无。工具默认 is_enabled=true，但不会自动挂到任何智能体上——
  要用的智能体需要在工具页或智能体编辑页手动勾选。
幂等：按 name 查重，重复执行无副作用。

执行：cd backend && ENV_FILE=.env.local .venv/bin/python scripts/migrations/20261106_020000_builtin_general_tools.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy.orm import Session

from app.db.models import Tool
from app.db.session import engine
from app.tools.langchain_tools import TOOL_DESCRIPTIONS

# 名称 → 参数声明。声明与 tools/builtin.BUILTIN_PARAMETERS 同源，
# 但这里要落进 tools.config 供工具页展示（BUILTIN_PARAMETERS 是"代码即真相"的另一份，
# tool_service._config_out 对 builtin 类型会用它覆盖 config.parameters，所以这里只存空壳即可）
_TOOLS: list[tuple[str, str]] = [
    ("text_stats", "统计文本的字符数、词数与行数。"),
    ("random_int", "生成指定区间内的随机整数。"),
    ("random_choice", "从若干候选项里随机挑一个。"),
    ("base64_encode", "把文本编码成 base64。"),
    ("base64_decode", "把 base64 解码回文本。"),
    ("json_query", "按点路径从 JSON 文档里取值。"),
    ("http_request", "发起 HTTP 请求并返回状态码与响应体；不能访问内网地址。"),
    ("web_search", "联网搜索网页，返回标题、链接、站点、日期与摘要。"),
]


def main() -> None:
    with Session(engine) as db:
        existing = {name for (name,) in db.query(Tool.name).filter(Tool.type == "builtin").all()}
        added = []
        for name, fallback_desc in _TOOLS:
            if name in existing:
                continue
            db.add(Tool(
                name=name,
                # 优先用装配时给模型看的那份描述，保证"工具页看到的"和"模型看到的"一致
                description=TOOL_DESCRIPTIONS.get(name, fallback_desc),
                type="builtin",
                config={},
                is_enabled=True,
            ))
            added.append(name)
        db.commit()
        if added:
            print(f"新增内置工具 {len(added)} 个：{', '.join(added)}")
        else:
            print("内置工具已齐，无需新增")


if __name__ == "__main__":
    main()
