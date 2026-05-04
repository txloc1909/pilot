"""Auth storage type definitions."""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional, Union

from pydantic import BaseModel


class ApiKeyCredential(BaseModel):
    type: Literal["api_key"] = "api_key"
    key: str


class OAuthCredential(BaseModel):
    type: Literal["oauth"] = "oauth"
    access_token: str
    refresh_token: Optional[str] = None
    expires: int = 0  # Unix ms
    scope: Optional[str] = None
    token_type: Optional[str] = None
    provider: Optional[str] = None


AuthCredential = Union[ApiKeyCredential, OAuthCredential]
AuthStorageData = Dict[str, AuthCredential]


class AuthStatus(BaseModel):
    configured: bool = False
    source: Optional[str] = None
    label: Optional[str] = None
