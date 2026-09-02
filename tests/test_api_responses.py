from enum import nonmember

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.common.codes import (
    AuthCode,
    CodeEnum,
    CommonCode,
    KnowledgeCode,
    SystemCode,
    validate_code_enums,
)
from app.common.exception import BusinessException
from app.common.handler import register_handlers
from app.common.response import R


class ItemRequest(BaseModel):
    item_id: int = Field(gt=0)


def build_app() -> FastAPI:
    app = FastAPI()
    register_handlers(app)

    @app.get("/success")
    def success() -> R[dict[str, int]]:
        return R.ok({"id": 123})

    @app.get("/missing")
    def missing() -> R[None]:
        raise BusinessException(KnowledgeCode.DOCUMENT_NOT_FOUND)

    @app.get("/forbidden")
    def forbidden() -> R[None]:
        raise BusinessException(AuthCode.FORBIDDEN)

    @app.post("/validate")
    def validate(payload: ItemRequest) -> R[dict[str, int]]:
        return R.ok({"item_id": payload.item_id})

    @app.get("/framework-error")
    def framework_error() -> R[None]:
        raise HTTPException(status_code=405)

    @app.get("/explode")
    def explode() -> R[None]:
        raise RuntimeError("不得返回给客户端的内部信息")

    return app


def test_success_response_uses_envelope() -> None:
    response = TestClient(build_app()).get("/success")

    assert response.status_code == 200
    assert response.json() == {
        "code": 0,
        "msg": "ok",
        "data": {"id": 123},
    }


def test_business_errors_are_http_200_with_null_data() -> None:
    client = TestClient(build_app())

    missing = client.get("/missing")
    forbidden = client.get("/forbidden")

    assert missing.status_code == 200
    assert missing.json() == {
        "code": 3001,
        "msg": "知识文档不存在",
        "data": None,
    }
    assert forbidden.status_code == 200
    assert forbidden.json() == {
        "code": 2003,
        "msg": "无操作权限",
        "data": None,
    }


def test_validation_error_is_http_200_with_field_and_reason() -> None:
    response = TestClient(build_app()).post("/validate", json={"item_id": 0})
    body = response.json()

    assert response.status_code == 200
    assert body["code"] == CommonCode.PARAM_ERROR.code
    assert body["data"] is None
    assert "item_id" in body["msg"]
    assert "greater than 0" in body["msg"]


def test_framework_http_errors_are_wrapped_with_http_200() -> None:
    client = TestClient(build_app())

    method_error = client.get("/framework-error")
    missing_route = client.get("/does-not-exist")

    assert method_error.status_code == 200
    assert method_error.json() == {
        "code": CommonCode.METHOD_NOT_ALLOWED.code,
        "msg": CommonCode.METHOD_NOT_ALLOWED.msg,
        "data": None,
    }
    assert missing_route.status_code == 200
    assert missing_route.json() == {
        "code": CommonCode.ROUTE_NOT_FOUND.code,
        "msg": CommonCode.ROUTE_NOT_FOUND.msg,
        "data": None,
    }


def test_unexpected_error_hides_internal_details() -> None:
    response = TestClient(build_app(), raise_server_exceptions=False).get("/explode")

    assert response.status_code == 200
    assert response.json() == {
        "code": SystemCode.INTERNAL_ERROR.code,
        "msg": SystemCode.INTERNAL_ERROR.msg,
        "data": None,
    }
    assert "不得返回" not in response.text


def test_business_exception_rejects_bare_string() -> None:
    with pytest.raises(TypeError, match="CommonCode.FAIL"):
        BusinessException("错误信息")  # type: ignore[arg-type]


def test_duplicate_codes_fail_with_both_owners() -> None:
    class FirstCode(CodeEnum):
        segment = nonmember((6000, 6999))
        FIRST = 6001, "第一个"

    class SecondCode(CodeEnum):
        segment = nonmember((6000, 6999))
        SECOND = 6001, "第二个"

    with pytest.raises(RuntimeError, match="FirstCode.FIRST.*SecondCode.SECOND"):
        validate_code_enums([FirstCode, SecondCode])
