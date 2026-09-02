from enum import nonmember, unique

from app.common.codes.base import CodeEnum


@unique
class CommonCode(CodeEnum):
    segment = nonmember((0, 1999))

    SUCCESS = 0, "ok"
    FAIL = 1, "操作失败，请稍后重试"
    PARAM_ERROR = 1000, "请求参数错误"
    ROUTE_NOT_FOUND = 1001, "请求接口不存在"
    METHOD_NOT_ALLOWED = 1002, "请求方法不允许"
