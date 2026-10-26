"""对话里工具结果的展示与持久化口径。

下发与落库分开：展示要小（控制 SSE 帧体积与页面渲染），落库要全（事后排查"接口到底返回了什么"）。
两个值只在这里定义一次——执行器（chat_runner）与历史消息接口（conversation_service）必须用同一份，
否则同一份数据在落库、实时事件、历史回看三处会出现三种长度。
"""

# 下发给前端、写进调用链（trace）的截断长度
TOOL_RESULT_PREVIEW_CHARS = 200

# 落库（messages.tool_calls）的截断长度；历史接口默认也按 PREVIEW 返回，只有排查时才取全量
TOOL_RESULT_STORE_CHARS = 8000
