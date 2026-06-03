from pydantic import BaseModel, Field
from typing import Optional, Literal


class ErrorResponse(BaseModel):
    success: Literal[False] = False
    error: str


class UploadRequest(BaseModel):
    imageBase64: str = Field(..., min_length=1)


class UploadResponse(BaseModel):
    success: Literal[True] = True
    imageUrl: str


class GenerateRequest(BaseModel):
    type: Literal["birthday", "anniversary"]
    templateUrl: str
    photoUrl: str
    name: str = Field(..., min_length=1)
    dob: Optional[str] = None
    years: Optional[str] = None


class GenerateResponse(BaseModel):
    success: Literal[True] = True
    imageUrl: str