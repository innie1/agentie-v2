import ipaddress
import socket
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from agents import function_tool

def _public_host(hostname: str) -> bool:
    try:
        for info in socket.getaddrinfo(hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
        return True
    except Exception:
        return False

@function_tool
def http_get(url: str) -> str:
    """Fetch text from a public HTTP(S) URL using a safe read-only GET request."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only valid http/https URLs are allowed.")
    if not _public_host(parsed.hostname):
        raise ValueError("Private, loopback, link-local, or reserved network targets are blocked.")
    req = Request(url, headers={"User-Agent": "Agentie/0.1"}, method="GET")
    with urlopen(req, timeout=12) as response:
        content_type = response.headers.get("Content-Type", "")
        if not any(t in content_type for t in ("text/", "application/json", "application/xml")):
            raise ValueError("Only text-like responses are supported.")
        data = response.read(120_000)
    return data.decode("utf-8", errors="replace")
