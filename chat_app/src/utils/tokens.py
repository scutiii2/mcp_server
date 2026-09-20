import hashlib
import hmac
import secrets

from src.utils.catalog import catalog


@catalog
def generate_otp_code(length: int = 10) -> str:
    return secrets.token_urlsafe(length)[:length]


@catalog
def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@catalog
def verify_token(token: str, token_hash: str) -> bool:
    return hmac.compare_digest(hash_token(token), token_hash)
