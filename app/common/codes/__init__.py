from collections.abc import Sequence

from app.common.codes.auth import AuthCode
from app.common.codes.base import CodeEnum
from app.common.codes.common import CommonCode
from app.common.codes.knowledge import KnowledgeCode
from app.common.codes.rag import RagCode
from app.common.codes.strategy import StrategyCode
from app.common.codes.system import SystemCode


ALL_CODE_ENUMS: list[type[CodeEnum]] = [
    CommonCode,
    AuthCode,
    KnowledgeCode,
    RagCode,
    StrategyCode,
    SystemCode,
]


def validate_code_enums(code_enums: Sequence[type[CodeEnum]]) -> None:
    owners: dict[int, str] = {}
    segments: list[tuple[int, int, str]] = []

    for enum_class in code_enums:
        segment = getattr(enum_class, "segment", None)
        if not isinstance(segment, tuple) or len(segment) != 2:
            raise RuntimeError(f"{enum_class.__name__}.segment 未正确声明")
        start, end = segment
        if start > end:
            raise RuntimeError(f"{enum_class.__name__}.segment 起始值不能大于结束值")
        segments.append((start, end, enum_class.__name__))

        for member in enum_class:
            owner = f"{enum_class.__name__}.{member.name}"
            if not start <= member.code <= end:
                raise RuntimeError(
                    f"{owner}={member.code} 不在号段 {start}-{end} 内"
                )
            previous = owners.get(member.code)
            if previous is not None:
                raise RuntimeError(
                    f"{member.code} 已被 {previous} 占用，不能再分配给 {owner}"
                )
            owners[member.code] = owner

    for index, (start, end, name) in enumerate(segments):
        for other_start, other_end, other_name in segments[index + 1:]:
            if max(start, other_start) <= min(end, other_end):
                raise RuntimeError(
                    f"{name} 号段 {start}-{end} 与 "
                    f"{other_name} 号段 {other_start}-{other_end} 重叠"
                )


validate_code_enums(ALL_CODE_ENUMS)

__all__ = [
    "ALL_CODE_ENUMS",
    "AuthCode",
    "CodeEnum",
    "CommonCode",
    "KnowledgeCode",
    "RagCode",
    "StrategyCode",
    "SystemCode",
    "validate_code_enums",
]
