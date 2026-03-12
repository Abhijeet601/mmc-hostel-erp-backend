import logging
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..auth import authenticate_admin, create_access_token
from ..config import settings
from ..database import get_db
from ..dependencies import get_current_admin
from ..schemas import AdminLoginRequest, AdminLoginResponse, AdminMeResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/login", response_model=AdminLoginResponse)
def admin_login(payload: AdminLoginRequest, request: Request, db: Session = Depends(get_db)) -> AdminLoginResponse:
    """Admin login endpoint with robust error handling.
    
    Returns:
        200: Successful login with access token
        401: Invalid credentials
        500: Never returned for auth failures (handled gracefully)
    """
    client_ip = request.client.host if request.client else "unknown"
    logger.info(f"Login attempt for username: {payload.username} from IP: {client_ip}")
    
    try:
        admin = authenticate_admin(db, payload.username, payload.password)
        
        if not admin:
            logger.warning(f"Failed login attempt for username: {payload.username} from IP: {client_ip} - invalid credentials")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password.",
            )

        expires = timedelta(minutes=settings.access_token_expire_minutes)
        token = create_access_token(subject=admin.username, expires_delta=expires)
        
        logger.info(f"Successful login for username: {payload.username} from IP: {client_ip}")
        
        return AdminLoginResponse(
            access_token=token,
            expires_in_seconds=settings.access_token_expire_minutes * 60,
            username=admin.username,
        )
        
    except HTTPException:
        # Re-raise HTTPExceptions (like 401) as-is
        raise
    except Exception as e:
        # Log the real exception internally but don't expose to client
        logger.error(f"Unexpected error during login for username: {payload.username} - {type(e).__name__}: {e}")
        # Return 401 instead of 500 to prevent leaking internal errors
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )


@router.get("/me", response_model=AdminMeResponse)
def admin_me(current_admin=Depends(get_current_admin)) -> AdminMeResponse:
    return AdminMeResponse(username=current_admin.username)
