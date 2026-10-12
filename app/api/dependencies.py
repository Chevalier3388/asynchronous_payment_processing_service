from secrets import compare_digest

from fastapi import Header, HTTPException, status

from app.core.config import settings


async def verify_api_key(
    api_key: str | None = Header(default=None, alias='X-API-Key'),
) -> None:
    if api_key is None or not compare_digest(
        api_key.encode('utf-8'),
        settings.api_key.encode('utf-8'),
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Invalid or missing API key',
        )