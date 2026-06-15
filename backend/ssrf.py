"""
SSRF (Server-Side Request Forgery) protection for URL fetching.

Blocks requests to private/internal IP ranges, link-local addresses,
loopback, and cloud metadata endpoints.
"""

import ipaddress
import socket
from urllib.parse import urlparse


# Private/internal IP ranges that should never be fetched
BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),        # RFC 1918 private
    ipaddress.ip_network("172.16.0.0/12"),      # RFC 1918 private
    ipaddress.ip_network("192.168.0.0/16"),     # RFC 1918 private
    ipaddress.ip_network("127.0.0.0/8"),        # Loopback
    ipaddress.ip_network("169.254.0.0/16"),     # Link-local (includes cloud metadata)
    ipaddress.ip_network("0.0.0.0/8"),          # "This" network
    ipaddress.ip_network("100.64.0.0/10"),      # Carrier-grade NAT (RFC 6598)
]

# Specific blocked addresses
BLOCKED_HOSTS = {
    "169.254.169.254",  # GCP/AWS/Azure metadata endpoint
    "metadata.google.internal",  # GCP metadata hostname
}

ALLOWED_SCHEMES = {"https"}


def is_url_safe(url: str) -> tuple[bool, str]:
    """
    Validate that a URL is safe to fetch server-side.

    Returns (is_safe, reason) tuple.
    Blocks private IPs, loopback, link-local, non-HTTPS schemes,
    and cloud metadata endpoints.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid URL format"

    # Only allow HTTPS
    if parsed.scheme not in ALLOWED_SCHEMES:
        return False, f"Scheme '{parsed.scheme}' not allowed. Only HTTPS is permitted."

    hostname = parsed.hostname
    if not hostname:
        return False, "URL must have a hostname"

    # Block known metadata hostnames
    if hostname in BLOCKED_HOSTS:
        return False, f"Hostname '{hostname}' is blocked (cloud metadata endpoint)"

    # Resolve hostname to IP and check against blocked networks
    try:
        addrinfo = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return False, f"Could not resolve hostname '{hostname}'"

    for addr in addrinfo:
        ip_str = addr[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue

        # Check against blocked networks
        for network in BLOCKED_NETWORKS:
            if ip in network:
                return False, f"IP {ip_str} is in blocked network {network}"

        # Block IPv6 loopback and link-local
        if ip.version == 6:
            if ip.is_loopback or ip.is_link_local or ip.is_private:
                return False, f"IPv6 address {ip_str} is blocked"

    return True, ""