import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from agents import function_tool


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if text:
            self.parts.append(text)


def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only public http/https URLs are allowed.")
    if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Localhost is not allowed.")
    try:
        for info in socket.getaddrinfo(parsed.hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise ValueError("Private or local network addresses are not allowed.")
    except socket.gaierror as exc:
        raise ValueError("Could not resolve host.") from exc


def browser_read_page_text(url: str) -> str:
    """Plain Python read-only page fetcher for internal systems and tests."""
    _validate_public_url(url)
    req = Request(url, headers={"User-Agent": "Agentie/0.4"})
    with urlopen(req, timeout=15) as response:
        content_type = response.headers.get("Content-Type", "")
        raw = response.read(1_000_000)
    if "text/html" not in content_type and "text/plain" not in content_type:
        raise ValueError("This browser tool currently supports HTML or plain text pages only.")
    text = raw.decode("utf-8", errors="replace")
    if "text/html" in content_type:
        parser = _TextExtractor()
        parser.feed(text)
        text = "\n".join(parser.parts)
    return text[:30000]


@function_tool
def browser_read_page(url: str) -> str:
    """Open a public webpage and return readable page text.

    This browser capability is intentionally read-only. It does not click,
    type, submit forms, download executables, or access private/local networks.
    """
    return browser_read_page_text(url)
