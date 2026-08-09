from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


def validate_public_https_url(url: str, *, allowed_hosts: set[str] | None = None) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("remote source must be an HTTPS URL without credentials")
    hostname = parsed.hostname.rstrip(".").lower()
    if allowed_hosts is not None and hostname not in allowed_hosts:
        raise ValueError(f"remote host is not allowed: {hostname}")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise ValueError("remote host cannot be resolved") from exc
    if not addresses:
        raise ValueError("remote host has no address")
    for value in addresses:
        address = ipaddress.ip_address(value.split("%", 1)[0])
        if not address.is_global:
            raise ValueError("private, local, reserved and link-local addresses are not allowed")
    return url
