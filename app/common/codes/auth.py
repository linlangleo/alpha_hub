from enum import nonmember, unique

from app.common.codes.base import CodeEnum


@unique
class AuthCode(CodeEnum):
    segment = nonmember((2000, 2999))

    LOGIN_REQUIRED = 2000, "请先登录"
    SESSION_EXPIRED = 2001, "登录已失效"
    INVALID_CREDENTIALS = 2002, "用户名或密码错误"
    FORBIDDEN = 2003, "无操作权限"
