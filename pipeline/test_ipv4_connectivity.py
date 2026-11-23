#!/usr/bin/env python3
"""Test IPv4/IPv6 connectivity and socket.getaddrinfo behavior."""
import socket
import sys

print("=== Testing socket.getaddrinfo from Python (no patch) ===")
results = socket.getaddrinfo('www.googleapis.com', 443)
for r in results[:5]:
    family_name = 'IPv4' if r[0] == socket.AF_INET else 'IPv6' if r[0] == socket.AF_INET6 else f'OTHER({r[0]})'
    print(f"  family={family_name} addr={r[4][0]}")

print("\n=== Testing socket.getaddrinfo from Python (with ipv4_google patch) ===")
sys.path.insert(0, '.')
import ipv4_google
import socket as socket_module
results = socket_module.getaddrinfo('www.googleapis.com', 443)
for r in results[:5]:
    family_name = 'IPv4' if r[0] == socket.AF_INET else 'IPv6' if r[0] == socket.AF_INET6 else f'OTHER({r[0]})'
    print(f"  family={family_name} addr={r[4][0]}")

# Verify patch is working
ipv4_first = all(r[0] == socket.AF_INET for r in results[:2])
print(f"\nPatch working (first 2 are IPv4): {ipv4_first}")
if not ipv4_first:
    sys.exit(1)
print("SUCCESS: IPv4 patch is working correctly")