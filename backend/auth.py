"""
Authentication module for JobSync.

Validates JWTs from Auth0 and provides FastAPI dependencies for
user authentication and authorization.
"""

import os
import logging
import time
from typing import Optional

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import jwt

from models import User, get_db

logger = logging.getLogger(__name__)

# Auth0 configuration from environment
AUTH0_DOMAIN = os.getenv("AUTH0_DOMAIN", "")
AUTH0_AUDIENCE = os.getenv("AUTH0_AUDIENCE", "https://jobsync/api")
ALGORITHMS = ["RS256"]

# JWKS cache
_jwks_cache = {"keys": None, "expires": 0}
_JWKS_CACHE_TTL = 3600  # 1 hour

security = HTTPBearer()


def _get_jwks() -> list[dict]:
    """Fetch Auth0 JWKS (JSON Web Key Set) with caching."""
    global _jwks_cache

    now = time.time()
    if _jwks_cache["keys"] and now < _jwks_cache["expires"]:
        return _jwks_cache["keys"]

    if not AUTH0_DOMAIN:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AUTH0_DOMAIN environment variable not set",
        )

    jwks_url = f"https://{AUTH0_DOMAIN}/.well-known/jwks.json"
    try:
        response = httpx.get(jwks_url, timeout=10.0)
        response.raise_for_status()
        jwks_data = response.json()
        _jwks_cache["keys"] = jwks_data.get("keys", [])
        _jwks_cache["expires"] = now + _JWKS_CACHE_TTL
        return _jwks_cache["keys"]
    except httpx.HTTPError as e:
        logger.error(f"Failed to fetch JWKS from Auth0: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to verify authentication credentials",
        )


def _get_rsa_key(kid: str) -> dict:
    """Find the RSA public key matching the key ID in the JWT header."""
    keys = _get_jwks()
    for key in keys:
        if key.get("kid") == kid:
            return key
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unable to find matching signing key",
    )


def verify_jwt(token: str) -> dict:
    """
    Validate a JWT token against Auth0's JWKS endpoint.

    Hardcodes algorithms=["RS256"] to prevent algorithm confusion attacks.
    Validates signature, issuer, audience, and expiry.
    """
    if not AUTH0_DOMAIN:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AUTH0_DOMAIN environment variable not set",
        )

    # Decode header without verification to get the key ID
    try:
        unverified_header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token format",
        )

    kid = unverified_header.get("kid")
    if not kid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing key ID",
        )

    # Get the matching RSA key from Auth0
    rsa_key = _get_rsa_key(kid)

    # Build the public key from JWKS
    from jwt.algorithms import RSAAlgorithm
    public_key = RSAAlgorithm.from_jwk(rsa_key)

    issuer = f"https://{AUTH0_DOMAIN}/"

    try:
        payload = jwt.decode(
            token,
            public_key,
            algorithms=ALGORITHMS,  # Hardcoded — never accept algorithm as parameter
            audience=AUTH0_AUDIENCE,
            issuer=issuer,
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except jwt.InvalidAudienceError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token audience",
        )
    except jwt.InvalidIssuerError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token issuer",
        )
    except jwt.InvalidTokenError as e:
        logger.warning(f"JWT validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """
    FastAPI dependency that extracts and validates the Bearer token,
    then looks up or creates the user in the database.

    Handles race conditions: if two concurrent requests try to create
    the same user, the IntegrityError on the unique auth0_id constraint
    is caught and the existing user is returned instead.
    """
    token = credentials.credentials
    payload = verify_jwt(token)

    auth0_id = payload.get("sub")
    if not auth0_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject claim",
        )

    # Look up existing user
    user = db.query(User).filter(User.auth0_id == auth0_id).first()
    if user:
        # Update last_login timestamp
        from datetime import datetime
        user.last_login = datetime.utcnow()
        db.commit()
        db.refresh(user)
        return user

    # Auto-provision new user from token claims
    email = payload.get("email", payload.get("nickname", ""))
    name = payload.get("name", payload.get("nickname", ""))
    # Auth0 stores profile picture in the "picture" claim
    avatar_url = payload.get("picture", "")

    new_user = User(
        auth0_id=auth0_id,
        email=email,
        name=name,
        avatar_url=avatar_url,
    )

    try:
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        logger.info(f"Auto-provisioned new user: {auth0_id} ({name} <{email}>)")
        return new_user
    except IntegrityError:
        # Race condition: another request created this user concurrently
        db.rollback()
        user = db.query(User).filter(User.auth0_id == auth0_id).first()
        if not user:
            # Should not happen, but handle gracefully
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create or find user",
            )
        return user