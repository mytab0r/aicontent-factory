#!/usr/bin/env python3
"""Force IPv4 for Google API domains to avoid TLS SSLEOF on broken IPv6 routes.

Root cause: runner container resolves www.googleapis.com -> AAAA first, connect succeeds
but TLS handshake fails with SSLEOF. Fix: monkey-patch socket.getaddrinfo to return
IPv4 addresses first for Google API domains.
"""
import socket
from functools import wraps

# Original getaddrinfo saved for restoration
_original_getaddrinfo = socket.getaddrinfo
_patched = False


# Google API domains that should use IPv4
_GOOGLE_API_DOMAINS = frozenset({
    'www.googleapis.com',
    'googleapis.com',
    'oauth2.googleapis.com',
    'youtube.googleapis.com',
    'www.youtube.com',
    'youtube.com',
    'accounts.google.com',
    'oauth2.googleapis.com',
})


def is_google_api_domain(host: str) -> bool:
    """Check if host is a Google API domain that should prefer IPv4."""
    if not host:
        return False
    host_lower = host.lower().rstrip('.')
    # Exact match or subdomain match
    for domain in _GOOGLE_API_DOMAINS:
        if host_lower == domain or host_lower.endswith('.' + domain):
            return True
    return False


def getaddrinfo_ipv4_first(host, port, family=0, type=0, proto=0, flags=0):
    """Wrapper that reorders getaddrinfo results to put IPv4 first for Google API domains."""
    results = _original_getaddrinfo(host, port, family, type, proto, flags)

    if not is_google_api_domain(host):
        return results

    # Separate IPv4 and IPv6 results
    ipv4_results = [r for r in results if r[0] == socket.AF_INET]
    ipv6_results = [r for r in results if r[0] == socket.AF_INET6]
    other_results = [r for r in results if r[0] not in (socket.AF_INET, socket.AF_INET6)]

    # Return IPv4 first, then IPv6, then others
    return ipv4_results + ipv6_results + other_results


# Mark the patched function for detection
getaddrinfo_ipv4_first._ipv4_patched = True


def install_ipv4_for_google_apis() -> None:
    """Install the IPv4-first patch for Google API domains."""
    global _patched
    if _patched:
        return
    socket.getaddrinfo = getaddrinfo_ipv4_first
    _patched = True


def uninstall_ipv4_for_google_apis() -> None:
    """Remove the IPv4-first patch, restoring original getaddrinfo."""
    global _patched
    if not _patched:
        return
    socket.getaddrinfo = _original_getaddrinfo
    _patched = False


# Auto-install when imported (can be disabled by setting env var before import)
import os
if os.environ.get('AICONTENT_DISABLE_IPV4_PATCH') != '1':
    install_ipv4_for_google_apis()