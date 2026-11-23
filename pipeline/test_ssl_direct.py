#!/usr/bin/env python3
"""Test direct SSL connection to Google API IPv4 addresses."""
import socket
import ssl
import sys

# Test IPv4 addresses from DNS
ipv4_addrs = [
    '172.217.112.4',
    '172.217.113.4', 
    '172.217.114.4',
    '172.217.115.4',
    '172.217.116.4',
    '172.217.117.4',
    '172.217.118.4',
    '172.217.119.4',
]

for ip in ipv4_addrs:
    print(f"\n=== Testing {ip} ===")
    try:
        sock = socket.create_connection((ip, 443), timeout=10)
        print(f"  TCP connect: OK")
        ctx = ssl.create_default_context()
        ssock = ctx.wrap_socket(sock, server_hostname='www.googleapis.com')
        print(f"  TLS handshake: OK (version={ssock.version()}, cipher={ssock.cipher()})")
        ssock.close()
        print(f"  SUCCESS")
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")

# Also test with httplib2 directly
print("\n=== Testing httplib2 with forced IPv4 ===")
try:
    import httplib2
    h = httplib2.Http()
    # Force IPv4 by using IP address directly
    resp, content = h.request('https://172.217.115.4/', 'GET', headers={'Host': 'www.googleapis.com'})
    print(f"  httplib2 status: {resp.status}")
except Exception as e:
    print(f"  httplib2 FAILED: {type(e).__name__}: {e}")

print("\nDone")