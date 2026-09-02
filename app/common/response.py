from typing import Generic, TypeVar

from pydantic import BaseModel

from app.common.codes.base import CodeEnum


T = TypeVar("T")


class R(BaseModel, Generic[T]):
    code: int = 0
    msg: str = "ok"
    data: T | None = None

    @classmethod
    def ok(cls, data: T | None = None) -> "R[T]":
        return cls(code=0, msg="ok", data=data)

    @classmethod
    def fail(cls, code: int, msg: str) -> "R[None]":
        if code == 0:
            raise ValueError("失败响应的 code 不能为 0")
        return R(code=code, msg=msg, data=None)

    @classmethod
    def from_error(cls, code_enum: CodeEnum) -> "R[None]":
        if not isinstance(code_enum, CodeEnum):
            raise TypeError("code_enum 必须是 CodeEnum 实例")
        return cls.fail(code_enum.code, code_enum.msg)
