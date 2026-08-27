import asyncio

from app.workflow.engine import build_workflow


async def main():
    graph_data = {
        "nodes": [
            {"id": "start_1", "type": "start", "config": {}},
            {"id": "tool_calc", "type": "tool", "config": {"tool_name": "calculator"}},
            {"id": "end_1", "type": "end", "config": {}},
        ],
        "edges": [
            {"from": "start_1", "to": "tool_calc"},
            {"from": "tool_calc", "to": "end_1"},
        ],
    }
    graph = build_workflow(graph_data)
    result = await graph.ainvoke({"input": '{"expression": "2+3*4"}', "steps": []})
    print("output:", result.get("output"))
    print("steps:", result.get("steps"))

    # 条件分支工作流
    print()
    print("=== 条件分支 ===")
    graph2 = build_workflow({
        "nodes": [
            {"id": "start_1", "type": "start", "config": {}},
            {"id": "tool_calc", "type": "tool", "config": {"tool_name": "calculator"}},
            {"id": "cond_1", "type": "condition", "config": {"expression": "'result' in str(output)"}},
            {"id": "end_ok", "type": "end", "config": {}},
            {"id": "end_fail", "type": "end", "config": {}},
        ],
        "edges": [
            {"from": "start_1", "to": "tool_calc"},
            {"from": "tool_calc", "to": "cond_1"},
            {"from": "cond_1", "to": "end_ok", "when": "true"},
            {"from": "cond_1", "to": "end_fail", "when": "false"},
        ],
    })
    result2 = await graph2.ainvoke({"input": '{"expression": "10/2"}', "steps": []})
    print("output:", result2.get("output"))
    print("steps:", result2.get("steps"))
    print("condition_result:", result2.get("condition_result"))


asyncio.run(main())
