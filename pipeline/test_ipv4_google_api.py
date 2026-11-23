#!/usr/bin/env python3
"""Test that Google API clients force IPv4 to avoid TLS SSLEOF on broken IPv6 routes.

Root cause: runner container resolves www.googleapis.com -> AAAA first, connect succeeds
but TLS handshake fails with SSLEOF. Fix: force AF_INET for Google API domains.
"""
import socket
from unittest.mock import patch, MagicMock


def test_getaddrinfo_prefers_ipv4_for_googleapis():
    """socket.getaddrinfo wrapper should return IPv4 addresses first for Google API domains."""
    from pipeline.ipv4_google import getaddrinfo_ipv4_first, _original_getaddrinfo

    # Mock original getaddrinfo returning AAAA first (broken IPv6 route)
    original_results = [
        (socket.AF_INET6, socket.SOCK_STREAM, 6, '', ('2001:4860:4840:400::8a', 443, 0, 0)),
        (socket.AF_INET6, socket.SOCK_STREAM, 6, '', ('2001:4860:4840:400::8b', 443, 0, 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('172.217.114.4', 443, 0, 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('172.217.112.4', 443, 0, 0)),
    ]

    with patch('pipeline.ipv4_google._original_getaddrinfo', return_value=original_results):
        results = getaddrinfo_ipv4_first('www.googleapis.com', 443)
        # IPv4 addresses should come first
        assert results[0][0] == socket.AF_INET, f"First result should be IPv4, got {results[0]}"
        assert results[1][0] == socket.AF_INET, f"Second result should be IPv4, got {results[1]}"
        # IPv6 should still be present but after IPv4
        ipv6_count = sum(1 for r in results if r[0] == socket.AF_INET6)
        assert ipv6_count == 2, f"Should preserve IPv6 addresses, got {ipv6_count}"


def test_getaddrinfo_unchanged_for_non_google():
    """Non-Google domains should use original getaddrinfo ordering."""
    from pipeline.ipv4_google import getaddrinfo_ipv4_first, _original_getaddrinfo

    original_results = [
        (socket.AF_INET6, socket.SOCK_STREAM, 6, '', ('::1', 80, 0, 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 80, 0, 0)),
    ]

    with patch('pipeline.ipv4_google._original_getaddrinfo', return_value=original_results):
        results = getaddrinfo_ipv4_first('example.com', 80)
        # Order should be preserved for non-Google domains
        assert results[0][0] == socket.AF_INET6, "Non-Google should preserve original order"


def test_google_domains_detected():
    """All Google API domains should be detected."""
    from pipeline.ipv4_google import is_google_api_domain

    assert is_google_api_domain('www.googleapis.com')
    assert is_google_api_domain('googleapis.com')
    assert is_google_api_domain('oauth2.googleapis.com')
    assert is_google_api_domain('youtube.googleapis.com')
    assert is_google_api_domain('www.youtube.com')  # YouTube API calls
    assert not is_google_api_domain('example.com')
    assert not is_google_api_domain('github.com')


def test_youtube_build_uses_ipv4():
    """googleapiclient.discovery.build should use IPv4 for YouTube API."""
    # This test verifies the integration point - the _youtube() function
    # should work with IPv4-forced socket
    from pipeline.ipv4_google import install_ipv4_for_google_apis

    # Install the patch
    install_ipv4_for_google_apis()

    # Verify socket.getaddrinfo is wrapped
    import socket as socket_module
    assert hasattr(socket_module.getaddrinfo, '_ipv4_patched'), "getaddrinfo should be patched"

    # Cleanup
    from pipeline.ipv4_google import uninstall_ipv4_for_google_apis
    uninstall_ipv4_for_google_apis()
    assert not hasattr(socket_module.getaddrinfo, '_ipv4_patched'), "getaddrinfo should be unpatched"


if __name__ == '__main__':
    test_getaddrinfo_prefers_ipv4_for_googleapis()
    test_getaddrinfo_unchanged_for_non_google()
    test_google_domains_detected()
    test_youtube_build_uses_ipv4()
    print("ok")