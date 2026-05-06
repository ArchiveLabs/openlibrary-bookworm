from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

_bearer = HTTPBearer()


def require_api_key(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> str:
    token = credentials.credentials
    if token not in settings.api_key_set:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key")
    return token
