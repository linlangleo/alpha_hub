import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.common.codes import AuthCode, CommonCode, SystemCode
from app.common.codes.base import CodeEnum
from app.common.exception import BusinessException
from app.common.response import R


logger = logging.getLogger(__name__)


def _json_error(code_enum: CodeEnum, msg: str | None = None) -> JSONResponse:
    response = R.fail(code_enum.code, code_enum.msg if msg is None else msg)
    return JSONResponse(status_code=200, content=response.model_dump())


def _log_business_exception(exc: BusinessException) -> None:
    module = exc.code // 1000 if exc.code >= 1000 else 0
    message = "business_error module=%s code=%s msg=%s"
    args = (module, exc.code, exc.msg)
    if exc.code == CommonCode.FAIL.code or exc.code >= 9000:
        logger.error(
            message,
            *args,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
    else:
        logger.warning(message, *args)


def _validation_message(exc: RequestValidationError) -> str:
    first_error = exc.errors()[0] if exc.errors() else {}
    location = first_error.get("loc", ())
    field = ".".join(str(part) for part in location if part not in {"body", "query", "path"})
    reason = str(first_error.get("msg", "格式不正确"))
    return f"参数 {field or 'request'} 校验失败：{reason}"


def _http_error_code(status_code: int) -> CodeEnum:
    mapping: dict[int, CodeEnum] = {
        401: AuthCode.LOGIN_REQUIRED,
        403: AuthCode.FORBIDDEN,
        404: CommonCode.ROUTE_NOT_FOUND,
        405: CommonCode.METHOD_NOT_ALLOWED,
    }
    return mapping.get(status_code, CommonCode.FAIL)


def register_handlers(app: FastAPI) -> None:
    @app.exception_handler(BusinessException)
    async def business_exception_handler(
        request: Request,
        exc: BusinessException,
    ) -> JSONResponse:
        del request
        _log_business_exception(exc)
        return _json_error(exc.code_enum, exc.msg)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        del request
        msg = _validation_message(exc)
        logger.warning(
            "validation_error module=1 code=%s msg=%s",
            CommonCode.PARAM_ERROR.code,
            msg,
        )
        return _json_error(CommonCode.PARAM_ERROR, msg)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        code_enum = _http_error_code(exc.status_code)
        logger.warning(
            "framework_http_error module=%s code=%s path=%s original_status=%s",
            code_enum.code // 1000 if code_enum.code >= 1000 else 0,
            code_enum.code,
            request.url.path,
            exc.status_code,
        )
        return _json_error(code_enum)

    @app.exception_handler(Exception)
    async def unexpected_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        logger.error(
            "system_error module=9 code=%s path=%s",
            SystemCode.INTERNAL_ERROR.code,
            request.url.path,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return _json_error(SystemCode.INTERNAL_ERROR)
