"""工作流图校验（FR-029）：并行 / 汇聚节点的结构规则，以及分支内节点的前驱计算。

两个纯函数、不依赖引擎，保存（POST / PUT）、编辑器测试运行、正式运行前都调用 validate_graph；
build_workflow 也会调用一次兜底（定时任务等没有调用方接 400 的路径按 failed 落库）。
不含并行节点的图永远通过：规则只针对 parallel / join。
"""
from collections import defaultdict

# 分支是线性链，只允许这五类节点；condition / loop / human_review / parallel / join 都会改变控制流，不进分支
BRANCH_ALLOWED_TYPES = {"agent", "tool", "kb_retrieval", "code", "http"}


def _index(graph: dict) -> tuple[dict[str, dict], dict[str, list[str]], dict[str, list[str]]]:
    nodes = {n["id"]: n for n in (graph.get("nodes") or []) if n.get("id")}
    out_edges: dict[str, list[str]] = defaultdict(list)
    in_edges: dict[str, list[str]] = defaultdict(list)
    for e in graph.get("edges") or []:
        src, dst = e.get("from"), e.get("to")
        if src in nodes and dst in nodes:
            out_edges[src].append(dst)
            in_edges[dst].append(src)
    return nodes, out_edges, in_edges


def _walk_branch(first: str, nodes: dict[str, dict], out_edges: dict[str, list[str]]) -> tuple[list[str], str | None]:
    """从分支首节点沿唯一出边走到 join。返回 (分支内节点 id 列表, 汇聚节点 id)；走不到 join（分叉、断头、成环）时为 None。"""
    chain: list[str] = []
    seen: set[str] = set()
    current = first
    while current in nodes and current not in seen:
        if nodes[current].get("type") == "join":
            return chain, current
        seen.add(current)
        chain.append(current)
        nexts = out_edges.get(current) or []
        if len(nexts) != 1:
            return chain, None
        current = nexts[0]
    return chain, None


def _branches(graph: dict) -> tuple[dict[str, dict], dict[str, list[str]], dict[str, list[tuple[list[str], str | None]]]]:
    """每个 parallel 节点的分支：{parallel_id: [(分支节点链, join_id 或 None), ...]}。"""
    nodes, out_edges, in_edges = _index(graph)
    result: dict[str, list[tuple[list[str], str | None]]] = {}
    for pid, node in nodes.items():
        if node.get("type") == "parallel":
            result[pid] = [_walk_branch(first, nodes, out_edges) for first in out_edges.get(pid, [])]
    return nodes, in_edges, result


def validate_graph(graph: dict) -> list[str]:
    """返回错误文本列表（空列表即通过），规则见 11-差距补齐PRD 4.5.3。"""
    errors: list[str] = []
    nodes, in_edges, branches = _branches(graph)
    tail_owner: dict[str, str] = {}  # 分支末节点 id → 所属 parallel id，供汇聚节点入边校验
    for pid, chains in branches.items():
        if len(chains) < 2:
            errors.append(f"并行节点 {pid} 至少需要 2 条分支")
        joins: set[str | None] = set()
        for chain, join_id in chains:
            for nid in chain:
                ntype = nodes[nid].get("type")
                if ntype not in BRANCH_ALLOWED_TYPES:
                    errors.append(f"并行分支内不支持 {ntype} 节点（{nid}）")
                ref = str((nodes[nid].get("config") or {}).get("input_ref") or "").strip()
                if ref in ("{{output}}", "output"):
                    errors.append(f"并行分支内的节点 {nid} 不能引用 {{{{output}}}}")
            joins.add(join_id)
            if chain and join_id:
                tail_owner[chain[-1]] = pid
        if chains and (len(joins) != 1 or None in joins):
            errors.append(f"并行节点 {pid} 的分支必须汇聚到同一个汇聚节点")
    for jid, node in nodes.items():
        if node.get("type") != "join":
            continue
        preds = in_edges.get(jid, [])
        owners = {tail_owner.get(p) for p in preds}
        if len(preds) < 2 or None in owners or len(owners) != 1:
            errors.append(f"汇聚节点 {jid} 的入边必须全部来自同一个并行节点且不少于 2 条")
    return errors


def branch_predecessors(graph: dict) -> dict[str, str]:
    """分支内每个节点的默认输入来源：首节点 → parallel 节点，其余 → 本分支上一节点。分支外的节点不在结果里。"""
    _, _, branches = _branches(graph)
    predecessors: dict[str, str] = {}
    for pid, chains in branches.items():
        for chain, _join in chains:
            prev = pid
            for nid in chain:
                predecessors[nid] = prev
                prev = nid
    return predecessors


def join_predecessors(graph: dict) -> dict[str, list[str]]:
    """每个 join 节点的入边来源（各分支末节点），供引擎按列表连边与收集输出；顺序按边定义顺序。"""
    _, in_edges, _ = _branches(graph)
    nodes = {n["id"]: n for n in graph.get("nodes") or []}
    return {jid: list(in_edges.get(jid, [])) for jid, n in nodes.items() if n.get("type") == "join"}
