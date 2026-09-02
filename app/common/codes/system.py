from enum import nonmember, unique

from app.common.codes.base import CodeEnum


@unique
class SystemCode(CodeEnum):
    segment = nonmember((9000, 9999))

    INTERNAL_ERROR = 9001, "系统内部错误"
    SERVICE_UNAVAILABLE = 9002, "基础服务暂不可用"
    UNKNOWN_SERVICE = 9003, "未知服务"
