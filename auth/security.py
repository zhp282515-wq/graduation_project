import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import jwt
from argon2 import PasswordHasher

PASSWORDS = PasswordHasher()
COOKIE = 'fanfan_session'
ISSUER = 'fanfan'
AUDIENCE = 'fanfan-web'
SESSION_SECONDS = 8 * 3600


@dataclass(frozen=True)
class Settings:
    secret: str
    secure: bool
    origins: frozenset[str]

    @classmethod
    def from_env(cls):
        secret = os.getenv('AUTH_JWT_SECRET', '')
        if len(secret.encode()) < 32:
            raise RuntimeError('AUTH_JWT_SECRET 必须配置至少 32 字节的随机密钥')
        origins = os.getenv('AUTH_ALLOWED_ORIGINS', 'http://127.0.0.1:5173,http://localhost:5173')
        return cls(secret, os.getenv('AUTH_COOKIE_SECURE', 'false').lower() == 'true',
                   frozenset(o.strip().rstrip('/') for o in origins.split(',') if o.strip()))

    def issue(self, user_id: str, sid: str) -> str:
        now = datetime.now(timezone.utc)
        return jwt.encode(dict(sub=user_id, jti=sid, iat=now, exp=now + timedelta(seconds=SESSION_SECONDS),
                               iss=ISSUER, aud=AUDIENCE), self.secret, algorithm='HS256')

    def decode(self, token: str) -> dict:
        return jwt.decode(token, self.secret, algorithms=['HS256'], issuer=ISSUER, audience=AUDIENCE,
                          options={'require': ['sub', 'jti', 'iat', 'exp', 'iss', 'aud']})

    def csrf(self, sid: str) -> str:
        return hmac.new(self.secret.encode(), f'csrf:{sid}'.encode(), hashlib.sha256).hexdigest()

    def trusted_origin(self, origin: str) -> bool:
        parsed = urlsplit(origin)
        return parsed.scheme in ('http', 'https') and origin.rstrip('/') in self.origins
