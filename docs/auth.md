# Auth

Core integrates with IAM (OIDC/SSO) and exposes lightweight helpers for parsing JWTs and injecting claims in FastAPI.

- `core_bluprint.auth.depends.JWTAuth` — required JWT dependency
- `core_bluprint.auth.depends.OptionalJWTAuth` — optional JWT dependency
- `core_bluprint.auth.schemas.UserClaims` — normalized user claims with roles

Usage example:

```python
from fastapi import APIRouter, Depends
from core_bluprint.auth.depends import JWTAuth
from core_bluprint.auth.protocols import OAuth2Settings

router = APIRouter()

@router.get("/me")
async def me(claims = Depends(JWTAuth(settings).get_claims)):
    return {"id": claims.id, "username": claims.username}
```

Claims normalization supports aliases (`owner`→`tenant`, `name`→`username`) and role checks via `is_admin`.
