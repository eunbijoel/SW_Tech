"""
API key validation and basic security utilities.
In production, replace with OAuth2 / JWT.
"""
from fastapi import Header, HTTPException, status

from backend.core.config import settings


async def verify_api_key(x_api_key: str = Header(default="")) -> str:
    """
    Simple header-based API key gate.
    Set SECRET_KEY in .env; pass X-API-Key header from the frontend.
    Disable in DEBUG mode for local development convenience.
    """
    if settings.DEBUG:
        return "debug"
    if not x_api_key or x_api_key != settings.SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
    return x_api_key
