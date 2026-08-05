"""
Authentication module for Joblign.

Validates JWTs from Auth0 and provides FastAPI dependencies for
user authentication and authorization.

Note: AUTH0_AUDIENCE defaults to "https://jobsync/api" — this is an opaque
API identifier registered in the Auth0 dashboard, not a user-visible
brand string. It is intentionally left as-is so existing issued tokens
keep validating; renaming it would require reconfiguring the Auth0
dashboard API identifier and breaking all active sessions.
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

# Acceptable token issuers. By default this is just the configured domain
# (e.g. "https://auth.ronning.systems/"), but Auth0's Custom Domain feature
# can issue tokens with either the custom-domain issuer OR the original
# tenant issuer depending on the flow path (e.g. social connections that
# route through login.<tenant>.auth0.com before bouncing to the SPA).
# Comma-separated env var so operators can add the original tenant issuer
# alongside the custom domain without code changes.
_default_issuer = f"https://{AUTH0_DOMAIN}/" if AUTH0_DOMAIN else ""
AUTH0_ISSUERS = [
    iss.strip() for iss in os.getenv("AUTH0_ISSUERS", _default_issuer).split(",")
    if iss.strip()
]

# Local-dev bypass. When AUTH_DISABLED is truthy, get_current_user returns a
# shared dev user without validating any token. Production must never set this.
# On test, an optional ACCOUNT_ID env var (1-10) selects which test profile to
# use, enabling dispersed sample data across multiple profiles.
AUTH_DISABLED = os.getenv("AUTH_DISABLED", "").lower() in ("1", "true", "yes")
_TEST_ACCOUNT_ID = os.getenv("ACCOUNT_ID", "").strip()
# Validate ACCOUNT_ID is 1-10 if provided; fall back to "local-dev" otherwise.
if _TEST_ACCOUNT_ID and _TEST_ACCOUNT_ID.isdigit() and 1 <= int(_TEST_ACCOUNT_ID) <= 10:
    DEV_USER_AUTH0_ID = f"test-account-{_TEST_ACCOUNT_ID}"
else:
    DEV_USER_AUTH0_ID = "local-dev"
del _TEST_ACCOUNT_ID  # clean up namespace

# JWKS cache keyed by issuer domain. Because Auth0 can issue tokens with
# either the custom domain or the original tenant as `iss`, we must fetch
# signing keys from the same domain that signed the token.
_jwks_cache: dict[str, dict] = {}
_JWKS_CACHE_TTL = 3600  # 1 hour

# auto_error=False so requests without an Authorization header don't 403 when
# auth is bypassed.
security = HTTPBearer(auto_error=AUTH_DISABLED is False)


def _normalize_issuer_domain(issuer: str) -> str:
    """Strip scheme and trailing path to leave a bare domain."""
    domain = issuer
    if domain.startswith("https://"):
        domain = domain[8:]
    elif domain.startswith("http://"):
        domain = domain[7:]
    return domain.rstrip("/")


def _get_jwks(issuer_domain: str) -> list[dict]:
    """Fetch Auth0 JWKS (JSON Web Key Set) for a specific issuer domain, with caching."""
    global _jwks_cache

    now = time.time()
    cached = _jwks_cache.get(issuer_domain)
    if cached and cached["keys"] and now < cached["expires"]:
        return cached["keys"]

    jwks_url = f"https://{issuer_domain}/.well-known/jwks.json"
    try:
        response = httpx.get(jwks_url, timeout=10.0)
        response.raise_for_status()
        jwks_data = response.json()
        _jwks_cache[issuer_domain] = {
            "keys": jwks_data.get("keys", []),
            "expires": now + _JWKS_CACHE_TTL,
        }
        return _jwks_cache[issuer_domain]["keys"]
    except httpx.HTTPError as e:
        logger.error(f"Failed to fetch JWKS from {issuer_domain}: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to verify authentication credentials",
        )


def _get_rsa_key(kid: str, issuer_domain: str) -> dict:
    """Find the RSA public key matching the key ID in the JWT header."""
    keys = _get_jwks(issuer_domain)
    for key in keys:
        if key.get("kid") == kid:
            return key
    logger.warning(
        f"No matching signing key (kid={kid}) from {issuer_domain} "
        f"(accepted issuers: {AUTH0_ISSUERS})"
    )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unable to find matching signing key",
    )


def verify_jwt(token: str) -> dict:
    """
    Validate a JWT token against the Auth0 JWKS endpoint of the token's issuer.

    Hardcodes algorithms=["RS256"] to prevent algorithm confusion attacks.
    Validates signature, issuer, audience, and expiry. Supports tokens issued
    by either a custom Auth0 domain or the original tenant domain.
    """
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

    # Decode payload without verification to discover the issuer. We validate
    # the issuer claim after signature verification, but we need it now to know
    # which JWKS endpoint to query for the correct signing key.
    try:
        unverified_payload = jwt.decode(token, options={"verify_signature": False})
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token format",
        )

    token_issuer = unverified_payload.get("iss", "")
    issuer_domain = _normalize_issuer_domain(token_issuer)
    if not issuer_domain:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing issuer claim",
        )

    # Get the matching RSA key from the issuer that signed the token
    rsa_key = _get_rsa_key(kid, issuer_domain)

    # Build the public key from JWKS
    from jwt.algorithms import RSAAlgorithm
    public_key = RSAAlgorithm.from_jwk(rsa_key)

    try:
        # python-jose's `issuer` accepts a string OR a list of strings —
        # the token just needs to match one of them.
        payload = jwt.decode(
            token,
            public_key,
            algorithms=ALGORITHMS,  # Hardcoded — never accept algorithm as parameter
            audience=AUTH0_AUDIENCE,
            issuer=AUTH0_ISSUERS if len(AUTH0_ISSUERS) > 1 else (AUTH0_ISSUERS[0] if AUTH0_ISSUERS else None),
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
        logger.warning(f"Invalid token issuer (expected one of: {AUTH0_ISSUERS})")
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
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """
    FastAPI dependency that extracts and validates the Bearer token,
    then looks up or creates the user in the database.

    When AUTH_DISABLED is set, returns a single shared dev user
    (auth0_id="local-dev") without validating any token.

    Handles race conditions: if two concurrent requests try to create
    the same user, the IntegrityError on the unique auth0_id constraint
    is caught and the existing user is returned instead.
    """
    if AUTH_DISABLED:
        return _get_or_create_dev_user(db)

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials",
        )
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


def _get_or_create_dev_user(db: Session) -> User:
    """Return the shared local-dev user, creating it on first request."""
    from datetime import datetime

    user = db.query(User).filter(User.auth0_id == DEV_USER_AUTH0_ID).first()
    if user:
        user.last_login = datetime.utcnow()
        db.commit()
        db.refresh(user)
        return user

    new_user = User(
        auth0_id=DEV_USER_AUTH0_ID,
        email="dev@localhost",
        name="Local Dev",
        avatar_url="",
    )
    try:
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        logger.info("Auto-provisioned local-dev user (AUTH_DISABLED=true)")
        return new_user
    except IntegrityError:
        db.rollback()
        user = db.query(User).filter(User.auth0_id == DEV_USER_AUTH0_ID).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create or find dev user",
            )
        return user