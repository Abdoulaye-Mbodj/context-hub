import hashlib
import hmac

from fastapi import Header, HTTPException, Request, status

from app.config import get_settings


def verify_integration_key(x_context_hub_key: str | None = Header(default=None)) -> None:
    expected = get_settings().integration_api_key
    if expected and not x_context_hub_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Clé d’intégration requise")
    if expected and not hmac.compare_digest(x_context_hub_key or "", expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Clé d’intégration invalide")


async def verify_odoo_signature(request: Request, x_context_hub_signature: str | None) -> bytes:
    body = await request.body()
    secret = get_settings().odoo_webhook_secret
    if not secret:
        return body
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    received = (x_context_hub_signature or "").removeprefix("sha256=")
    if not hmac.compare_digest(received, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Signature Odoo invalide")
    return body
