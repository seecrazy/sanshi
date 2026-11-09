"""统一业务异常。API 层与 Job 层都不允许绕过这些异常直接改数据。"""


class BizError(Exception):
    """业务校验失败 -> 400"""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class StateConflictError(BizError):
    """状态机迁移失败（并发/非法迁移）-> 409"""

    def __init__(self, message: str = "状态已变更，请刷新后重试"):
        super().__init__(message)


class PermissionDeniedError(BizError):
    def __init__(self, message: str = "无权操作"):
        super().__init__(message)


class NotFoundError(BizError):
    def __init__(self, message: str = "资源不存在"):
        super().__init__(message)
