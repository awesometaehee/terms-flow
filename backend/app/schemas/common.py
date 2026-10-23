from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

NonBlankStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
# 파일명·식별자에 쓰이는 코드값
Code = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", max_length=50)]
Key = Annotated[
    str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$", max_length=100)
]


class RequestModel(BaseModel):
    """알 수 없는 필드는 오타로 보고 거부한다."""

    model_config = ConfigDict(extra="forbid")


class ResponseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
