from enum import nonmember, unique

from app.common.codes.base import CodeEnum


@unique
class RagCode(CodeEnum):
    segment = nonmember((4000, 4999))

    SEARCH_FAILED = 4000, "知识检索失败"
    ANSWER_FAILED = 4001, "AI 知识问答失败"
