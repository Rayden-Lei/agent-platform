def test_list_tools(client, auth_headers):
    res = client.get("/api/v1/tools", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body["items"], list)
    assert body["page"] == 1 and body["total"] >= len(body["items"])


def test_tool_crud(client, auth_headers):
    t = client.post("/api/v1/tools", headers=auth_headers, json={
        "name": "pytest-tool", "description": "测试工具", "type": "builtin", "config": {}, "timeout": 30,
    })
    assert t.status_code == 200, t.text
    tid = t.json()["id"]

    # 测试接口（内置工具 name 未知也会返回结果）
    r = client.post(f"/api/v1/tools/{tid}/test", headers=auth_headers, json={"args": {}})
    assert r.status_code == 200

    d = client.delete(f"/api/v1/tools/{tid}", headers=auth_headers)
    assert d.status_code == 200


# ---------- 计算器的资源上限：9**9**9 这类大整数运算持有 GIL，整个后端会停摆（2026-09-25） ----------

import os  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from app.tools.executor import _safe_eval  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("expr,expected", [
    ("2+3*4", 14), ("2**10", 1024), ("(1+2)/4", 0.75), ("-3**2", -9), ("2**-1", 0.5), ("1.5*2", 3.0),
    ("2**1000 - 2**1000", 0),  # 上限以内的大整数照常算
])
def test_calculator_still_evaluates_normal_expressions(expr, expected):
    assert _safe_eval(expr) == expected


@pytest.mark.parametrize("expr", ["9**9**9", "10**100000", "99999999999**9999", "'a'*10**9"])
def test_calculator_rejects_huge_computation_without_hanging(expr):
    """放在子进程里跑并限时：修复前这些表达式会算到超时，不能让它卡住测试进程本身。"""
    code = (
        "from app.tools.executor import _safe_eval\n"
        f"try:\n    _safe_eval({expr!r})\n"
        "except (ValueError, OverflowError) as e:\n    print('REJECTED', e)\n"
        "else:\n    print('ACCEPTED')\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=15,
                       cwd=BACKEND_DIR, env={**os.environ, "PYTHONPATH": str(BACKEND_DIR)})
    assert "REJECTED" in r.stdout, r.stdout + r.stderr


@pytest.mark.parametrize("expr,message", [
    ("(-8)**0.5", "实数"),          # 负数开方得复数，JSON 序列化不了
    ("True+1", "仅支持"),            # 布尔常量
    ("1j*2", "仅支持"),              # 复数常量
    ("__import__('os')", "仅支持"),  # 函数调用
    ("1" + "+1" * 150, "过长"),      # 超长表达式（也挡住深嵌套括号让 ast.parse 递归过深）
    ("2**4000", "过大"),             # 结果超过上限
])
def test_calculator_rejects_unsafe_expressions(expr, message):
    with pytest.raises(ValueError, match=message):
        _safe_eval(expr)
