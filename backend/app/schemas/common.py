from typing import Generic, TypeVar, Optional, Any
from pydantic import BaseModel

T = TypeVar("T")


class SuccessResponse(BaseModel, Generic[T]):
    success: bool = True
    data: Optional[T] = None
    message: str = "OK"


class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    detail: str = ""


def success(data: Any = None, message: str = "OK") -> dict:
    return {"success": True, "data": data, "message": message}


def error(err: str, detail: str = "") -> dict:
    return {"success": False, "error": err, "detail": detail}
