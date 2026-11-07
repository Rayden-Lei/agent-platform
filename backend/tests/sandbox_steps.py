"""代码节点 steps 的期望值构造：按当前环境的沙箱实际模式生成，不在用例里写死 "code"。

为什么需要这一层：`app/workflow/engine.py` 的代码节点在**真的走 bwrap** 时把 steps 记成
`code:bwrap`，只有降级（basic）时才是 `code`。这个后缀是有意义的标记 —— 运行详情页要能
看出代码到底在不在真沙箱里跑（docs/15 WF-18 / 决策 D-33），所以生产代码不改。

于是同一个期望值没法写死：
  - macOS 本机、没装 bubblewrap 的机器（probe() 为 basic）：steps 是 `code`；
  - Linux CI、装了 bwrap 且能建命名空间的机器（probe() 为 bwrap）：steps 是 `code:bwrap`。
写死任何一种都只能在一半环境上通过（2026-11 前写死 `code`，Linux CI 上整片红）。

为什么这不等于放松断言：期望值由 `sandbox.probe()` 独立推出，**不是**从执行结果里反读
（反读会让断言恒真）。而两个分支各自的字面值由 test_workflow_engine.py 里
`test_code_step_marker_bwrap` / `test_code_step_marker_degraded` 用打桩钉死，
所以"按环境生成期望值"仍然是在验证引擎真的按沙箱模式加了这个后缀。
"""
from app.runtime import sandbox


def code_step() -> str:
    """一次代码节点在 steps 里的期望值：真沙箱是 `code:bwrap`，降级是 `code`。"""
    if sandbox.probe().mode == sandbox.MODE_BWRAP:
        return f"code:{sandbox.MODE_BWRAP}"
    return "code"


def code_steps(count: int = 1) -> list[str]:
    """连续 count 个代码节点的期望 steps（每个代码节点都会追加一条）。"""
    return [code_step()] * count
