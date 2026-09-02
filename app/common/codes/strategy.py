from enum import nonmember, unique

from app.common.codes.base import CodeEnum


@unique
class StrategyCode(CodeEnum):
    segment = nonmember((5000, 5999))

    STRATEGY_NOT_FOUND = 5000, "策略不存在"
