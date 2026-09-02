from app.common.codes.base import CodeEnum


class BusinessException(Exception):
    def __init__(
        self,
        code_enum: CodeEnum,
        msg: str | None = None,
    ) -> None:
        if not isinstance(code_enum, CodeEnum):
            raise TypeError(
                "BusinessException 第一个参数必须是 CodeEnum 实例；"
                "自定义提示请使用 BusinessException(CommonCode.FAIL, \"你的提示\")"
            )
        self.code_enum = code_enum
        self.code = code_enum.code
        self.msg = code_enum.msg if msg is None else msg
        super().__init__(self.msg)
