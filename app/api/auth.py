from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
        )
    user_id = get_session_user_id(credentials.credentials)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录已失效",
        )
    return user_id


@router.post("/login")
def login(payload: LoginRequest) -> dict[str, str]:
    user = authenticate_user(payload.username.strip(), payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    token = create_session(user["id"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "username": user["username"],
    }


@router.get("/check")
def check_login(user_id: int = Depends(require_user_id)) -> dict[str, object]:
    return {"authenticated": True, "user_id": user_id}


@router.post("/logout")
def logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, bool]:
    if credentials is not None:
        delete_session(credentials.credentials)
    return {"success": True}
