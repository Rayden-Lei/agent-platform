"""对话调用链（docs/15 3.4）：每完成一步产出一条 TraceStep，装配页调试以 SSE trace 事件下发。

TraceStep 是全平台共用的结构：{id, type, name, status, started_at, duration_ms, input, output, meta}，
type 取 rewrite / retrieve / llm / tool。第 2 批 OP-08 会把线上对话的同一结构写进 run_nodes，
运行详情的"调用链"页签与调试面板用同一组前端组件，所以字段只在这里定义。
"""
import time
import uuid
from datetime import datetime, timedelta, timezone

# 命中切片的定位信息：解析时写进切片 meta 的这几个键（rag/parser.py：pdf 的页码、docx 的标题、表格的行号）
HIT_LOCATION_KEYS = ("type", "page", "row", "heading")


class Clock:
    """一步的起止：墙上时间记开始时刻（给人看），单调时钟算耗时（不受系统校时影响）。
    stop() 定格结束时刻：模型调用在最后一个分块到达时就结束了，步骤却要等下一个事件才能收尾。"""

    def __init__(self, t0: float | None = None):
        now = time.perf_counter()
        self._t0 = now if t0 is None else t0
        self.started_at = datetime.now(timezone.utc) - timedelta(seconds=now - self._t0)
        self._t1: float | None = None

    def stop(self) -> "Clock":
        self._t1 = time.perf_counter()
        return self

    def successor(self) -> "Clock":
        """从本步结束时刻开始计时的下一步（工具在模型调用结束后才开始执行）。"""
        return Clock(self._t1 if self._t1 is not None else None)

    def elapsed_ms(self) -> int:
        return int(((self._t1 if self._t1 is not None else time.perf_counter()) - self._t0) * 1000)


def make_step(type_: str, name: str, clock: Clock, *, input=None, output=None, meta: dict | None = None, status: str = "success") -> dict:
    return {
        "id": uuid.uuid4().hex[:12], "type": type_, "name": name, "status": status,
        "started_at": clock.started_at.isoformat(), "duration_ms": clock.elapsed_ms(),
        "input": input, "output": output, "meta": meta or {},
    }


def retrieve_step(kb_name: str, query: str, result: dict, clock: Clock) -> dict:
    """一个 (知识库, 查询) 的检索步骤。命中只带定位与各项分数，不重复带正文（正文在 citations 事件里）。"""
    stats = result.get("stats", {})
    hits = [{
        "chunk_id": item["chunk_id"], "doc_id": item.get("doc_id"), "doc_name": item.get("doc_name"), "score": item.get("score"),
        "vector_score": item.get("vector_score"), "keyword_score": item.get("keyword_score"), "rerank_score": item.get("rerank_score"),
        "location": {k: (item.get("meta") or {})[k] for k in HIT_LOCATION_KEYS if k in (item.get("meta") or {})},
    } for item in result.get("items", [])]
    meta = {key: stats.get(key) for key in ("candidate_count", "returned", "acl_rejected", "kb_denied", "rerank_mode", "timings")}
    status = "denied" if stats.get("kb_denied") else "success"
    return make_step("retrieve", kb_name, clock, input={"query": query}, output=hits, meta=meta, status=status)
