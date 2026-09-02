from enum import Enum


class CodeEnum(Enum):
    """Base class for typed application response codes."""

    segment: tuple[int, int]
    code: int
    msg: str

    def __new__(cls, code: int, msg: str) -> "CodeEnum":
        obj = object.__new__(cls)
        obj._value_ = code
        obj.code = code
        obj.msg = msg
        return obj
