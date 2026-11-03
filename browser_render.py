"""Opt-in graphical Chromium/Xvfb fallback for HTML requiring JavaScript.

Only AFTER a successful 200 response through the established robots/public-IP
static transport. Never uses it for 403, CAPTCHA, authentication or denied
robots, and never exposes local browser profiles or server memory to clients.
"""
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
from threading import BoundedSemaphore
from urllib.parse import urlsplit

from product_intake import validate_product_url

_LOCK=BoundedSemaphore(1)
MAX_RENDER_BYTES=1_800_000
CHALLENGE_MARKERS=(
    b"cf-mitigated",b"captcha",b"verify you are human",
    b"challenge-platform",b"access denied",
)

def approved_static_body(raw):
    """A successful, non-challenge robots-approved HTTP 200 body is mandatory."""
    if not isinstance(raw,bytes) or not raw or len(raw)>MAX_RENDER_BYTES:
        return False
    needle=raw[:50000].lower()
    return not any(marker in needle for marker in CHALLENGE_MARKERS)

def _public_pinned_ipv4(host):
    addresses=socket.getaddrinfo(host,443,socket.AF_INET,socket.SOCK_STREAM)
    for item in addresses:
        ip=item[4][0]
        if ipaddress.ip_address(ip).is_global:
            return ip
    raise ValueError("NO_PUBLIC_BROWSER_IP")

def rendered_browser_document(url,static_body,runner=None,enabled=None):
    """Return isolated DOM bytes or raise a safe, audit-friendly exception."""
    if enabled is None:
        enabled=os.environ.get("TRACECART_GRAPHICAL_BROWSER_FALLBACK","0")=="1"
    if not enabled:
        raise ValueError("GRAPHICAL_BROWSER_NOT_ENABLED")
    if not approved_static_body(static_body):
        raise ValueError("BROWSER_DENIED_SOURCE_OR_CHALLENGE")
    url=validate_product_url(url)
    parts=urlsplit(url)
    if parts.scheme!="https" or not parts.hostname or parts.port not in (None,443):
        raise ValueError("UNSAFE_RENDER_URL")
    if not _LOCK.acquire(blocking=False):
        raise ValueError("GRAPHICAL_BROWSER_BUSY")
    try:
        pinned_ip=_public_pinned_ipv4(parts.hostname)
        script=Path(__file__).resolve().parent/"browser_render.js"
        proc=(runner or subprocess.run)(
            ["node",str(script),url,parts.hostname,pinned_ip],
            capture_output=True,timeout=19,check=False,
        )
        if proc.returncode!=0 or not proc.stdout or len(proc.stdout)>MAX_RENDER_BYTES+2000:
            raise ValueError("GRAPHICAL_BROWSER_RENDER_FAILED")
        payload=json.loads(proc.stdout)
        if (payload.get("source_url")!=url or
            payload.get("browser_request_scope")!="SAME_ORIGIN_HTTPS_ONLY_PINNED_PUBLIC_IP"
            or payload.get("render_method")!="ISOLATED_XVFB_CHROMIUM"):
            raise ValueError("GRAPHICAL_RENDER_PROVENANCE_NOT_CONFIRMED")
        raw=payload["html"].encode("utf-8")
        if not approved_static_body(raw):
            raise ValueError("BROWSER_RENDERED_CHALLENGE_OR_BAD_HTML")
        return raw
    except (subprocess.TimeoutExpired,OSError,KeyError,TypeError,
            UnicodeError,ValueError,json.JSONDecodeError) as exc:
        raise ValueError("GRAPHICAL_BROWSER_SOURCE_NOT_VERIFIED") from exc
    finally:
        _LOCK.release()
