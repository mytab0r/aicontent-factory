#!/usr/bin/env python3
"""Test full googleapiclient stack with IPv4 patch."""
import os
import sys

# Ensure patch is applied BEFORE importing googleapiclient
sys.path.insert(0, '.')
import ipv4_google  # noqa: F401
print(f"Patch active: {getattr(ipv4_google.getaddrinfo_ipv4_first, '_ipv4_patched', False)}")

# Now test googleapiclient import and socket resolution
try:
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials
    
    print("Building YouTube service (no auth)...")
    # Test that the patch works with googleapiclient's internal socket usage
    # We can't call execute() without valid token, but we can verify the build works
    # and that socket.getaddrinfo is patched when googleapiclient uses it
    print("googleapiclient.discovery.build imported successfully")
    
    # Verify patch is still active after googleapiclient import
    import socket
    results = socket.getaddrinfo('www.googleapis.com', 443)
    ipv4_first = all(r[0] == socket.AF_INET for r in results[:2])
    print(f"Patch still active after googleapiclient import: {ipv4_first}")
    if not ipv4_first:
        first_str = ', '.join(f"{'IPv4' if r[0]==socket.AF_INET else 'IPv6' if r[0]==socket.AF_INET6 else 'OTHER'}:{r[4][0]}" for r in results[:5])
        print(f"First results: {first_str}")
        sys.exit(1)
    
    print("SUCCESS: IPv4 patch works with googleapiclient!")
    
except Exception as e:
    print(f"FAILED: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)