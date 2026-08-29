class BizError(Exception):
    """业务异常：service 层抛出，由全局 exception handler 转为统一错误响应。

    携带 HTTP 状态码与可读信息，避免 service 层依赖 FastAPI 的 HTTPException。
    对外响应保持 FastAPI 默认的 {"detail": ...} 结构，前端契约不变。
    """

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)
