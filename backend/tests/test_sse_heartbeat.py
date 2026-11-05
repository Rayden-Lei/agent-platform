"""SSE 心跳与前端读超时的契约（docs/04 第 5 节）。

为什么要有心跳：模型首字节慢、工具执行久、上游半开连接时，客户端长时间收不到任何字节。
浏览器与中间代理会因此掐断连接，前端也只能一直显示"正在思考"——2026-11-06 使用者反馈
"思考过程卡在 30.9 秒不动"就是这个现象。

心跳是 SSE 规范的注释行（以 `:` 开头），符合规范的客户端天然忽略；本项目前端按
`startsWith("data: ")` 判断事件，注释行被跳过，解析器不用改。
"""
import asyncio

import pytest

import app.api.v1.chat as chatmod
from app.api.v1.chat import sse_stream


@pytest.fixture
def fast_heartbeat(monkeypatch):
    """把心跳压到 0.05 秒，让测试不必真等 15 秒。"""
    monkeypatch.setattr(chatmod, "SSE_HEARTBEAT_SECONDS", 0.05)


def _frames(chunks: list[str]) -> list[str]:
    return [c.strip() for c in chunks]


@pytest.mark.anyio
async def test_heartbeat_emitted_during_silence(fast_heartbeat):
    """事件之间静默超过心跳间隔时，插入 `: ping` 注释帧。"""

    async def events():
        yield {"type": "delta", "content": "a"}
        await asyncio.sleep(0.2)      # 远超 0.05 秒的心跳间隔
        yield {"type": "done"}

    frames = _frames([f async for f in sse_stream(events())])

    assert frames[0].startswith("data: ")
    assert ": ping" in frames, f"静默期没有心跳：{frames}"
    # 最后一个 data 帧必须是 done：心跳只能插在事件之间，不能把真实事件挤掉
    data_frames = [f for f in frames if f.startswith("data: ")]
    assert data_frames[-1].startswith("data: "), f"真实事件被心跳挤掉了：{frames}"
    assert "done" in data_frames[-1]


@pytest.mark.anyio
async def test_no_heartbeat_when_events_are_fast(fast_heartbeat):
    """事件来得比心跳间隔快时，不该插入多余帧。"""

    async def events():
        for i in range(3):
            yield {"type": "delta", "content": str(i)}

    frames = _frames([f async for f in sse_stream(events())])

    assert len(frames) == 3
    assert all(f.startswith("data: ") for f in frames)


@pytest.mark.anyio
async def test_heartbeat_frame_is_sse_comment(fast_heartbeat):
    """心跳必须是 SSE 注释行，否则前端解析器会把它当成坏事件丢掉整块。"""

    async def events():
        await asyncio.sleep(0.2)
        yield {"type": "done"}

    frames = _frames([f async for f in sse_stream(events())])
    pings = [f for f in frames if f.startswith(":")]

    assert pings, f"没有心跳帧：{frames}"
    for p in pings:
        assert p == ": ping"
        assert not p.startswith("data: "), "心跳不能带 data: 前缀，前端会当事件解析"


@pytest.mark.anyio
async def test_stream_ends_cleanly_without_trailing_heartbeat(fast_heartbeat):
    """流正常结束时不追加心跳，也不吞掉最后一个事件。"""

    async def events():
        yield {"type": "delta", "content": "x"}
        yield {"type": "done"}

    frames = _frames([f async for f in sse_stream(events())])

    assert len(frames) == 2
    assert '"type": "done"' in frames[-1]
