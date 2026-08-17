from ipaddress import ip_address

from fastapi import Request


def request_client_ip(request: Request) -> str:
    """Return the normalized client address supplied by the trusted edge."""

    direct = request.client.host if request.client is not None else None
    for candidate in (request.headers.get("x-real-ip"), direct):
        if not candidate:
            continue
        try:
            return ip_address(candidate.strip()).compressed
        except ValueError:
            continue
    return "unknown"
