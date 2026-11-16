"""URL syntax policy; executor must enforce DNS/network navigation policy."""
from urllib.parse import urlsplit


def target_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValueError("Invalid target URL") from None
    if (value != value.strip() or any(ord(c) <= 32 for c in value) or
            parsed.scheme not in {"http", "https"} or not parsed.hostname or
            parsed.username is not None or parsed.password is not None):
        raise ValueError("Use an HTTP(S) URL without whitespace or embedded credentials")
    return value
