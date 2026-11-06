"""Environment-only auth configuration. Never put keys in source control."""
from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False)


def origin(value: str, development: bool) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname
            or parsed.username or parsed.password or parsed.path or parsed.query
            or parsed.fragment or '*' in value):
        raise ValueError('Origins must be explicit scheme://host[:port] values without paths')
    if parsed.scheme != 'https' and not (development and parsed.hostname == 'localhost'):
        raise ValueError('HTTP origins are allowed only for localhost development')
    return value


@dataclass(frozen=True)
class AuthSettings:
    supabase_url: str = ''
    publishable_key: str = field(default='', repr=False)
    development: bool = False
    frontend_origins: tuple[str, ...] = ()
    backend_origin: str = ''
    email_frontend_origin: str = ''
    flow_encryption_key: str = field(default='', repr=False)
    same_site: str = 'lax'
    refresh_max_age: int = 60 * 60 * 24 * 30

    def __post_init__(self):
        for value in self.frontend_origins + ((self.backend_origin,) if self.backend_origin else ()):
            origin(value, self.development)
        if self.email_frontend_origin:
            origin(self.email_frontend_origin, self.development)
            if self.email_frontend_origin not in self.frontend_origins:
                raise ValueError('AUTH_EMAIL_FRONTEND_ORIGIN must be an allowed frontend origin')
        if self.same_site not in {'lax', 'strict', 'none'}:
            raise ValueError('AUTH_COOKIE_SAMESITE must be lax, strict or none')
        if self.development and self.same_site == 'none':
            raise ValueError('SameSite=None requires HTTPS/Secure production cookies')
        if not 60 <= self.refresh_max_age <= 60 * 60 * 24 * 365:
            raise ValueError('AUTH_REFRESH_COOKIE_MAX_AGE must be between 60 seconds and 365 days')
        if self.supabase_url:
            parsed = urlsplit(self.supabase_url)
            if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                    or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'', '/'}):
                raise ValueError('SUPABASE_URL must be an HTTPS project URL')

    @property
    def secure(self):
        return not self.development

    @property
    def access_cookie(self):
        return 'bs_access' if self.development else '__Host-bs_access'

    @property
    def refresh_cookie(self):
        return 'bs_refresh' if self.development else '__Host-bs_refresh'

    @property
    def trusted_origins(self):
        return self.frontend_origins + ((self.backend_origin,) if self.backend_origin else ())

    @classmethod
    def from_env(cls):
        mode = os.getenv('APP_ENV', 'production')
        if mode not in {'development', 'production'}:
            raise ValueError('APP_ENV must be development or production')
        development = mode == 'development'
        defaults = 'http://localhost:3000' if development else ''
        return cls(
            supabase_url=os.getenv('SUPABASE_URL', '').rstrip('/'),
            publishable_key=os.getenv('SUPABASE_PUBLISHABLE_KEY', ''),
            development=development,
            frontend_origins=tuple(v.strip() for v in os.getenv('AUTH_FRONTEND_ORIGINS', defaults).split(',') if v.strip()),
            backend_origin=os.getenv('AUTH_BACKEND_ORIGIN', 'http://localhost:8000' if development else ''),
            flow_encryption_key=os.getenv('AUTH_FLOW_ENCRYPTION_KEY', ''),
            email_frontend_origin=os.getenv('AUTH_EMAIL_FRONTEND_ORIGIN', ''),
            same_site=os.getenv('AUTH_COOKIE_SAMESITE', 'lax'),
            refresh_max_age=int(os.getenv('AUTH_REFRESH_COOKIE_MAX_AGE', str(60 * 60 * 24 * 30))),
        )
