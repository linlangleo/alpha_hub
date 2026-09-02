from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.common.codes import AuthCode
from app.common.exception import BusinessException
from app.common.response import R
from app.core.redis_client import (
    create_session,
    delete_session,
    get_session_user_id,
)
from app.repositories.user_repository import authenticate_user


router = APIRouter(prefix="/api/auth", tags=["auth"])
bearer_scheme = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=128)


def require_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> int:
    if credentials is None:
        raise BusinessException(AuthCode.LOGIN_REQUIRED)
    user_id = get_session_user_id(credentials.credentials)
    if user_id is None:
        raise BusinessException(AuthCode.SESSION_EXPIRED)
    return user_id


@router.post("/login")
def login(payload: LoginRequest) -> R[dict[str, str]]:
    user = authenticate_user(payload.username.strip(), payload.password)
    if user is None:
        raise BusinessException(AuthCode.INVALID_CREDENTIALS)
    token = create_session(user["id"])
    return R.ok({
        "access_token": token,
        "token_type": "bearer",
        "username": user["username"],
    })


@router.get("/check-login")
def check_login(user_id: int = Depends(require_user_id)) -> R[dict[str, object]]:
    return R.ok({"authenticated": True, "user_id": user_id})


@router.post("/logout")
def logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> R[dict[str, bool]]:
    if credentials is not None:
        delete_session(credentials.credentials)
    return R.ok({"success": True})
