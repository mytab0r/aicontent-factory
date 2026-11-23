#!/usr/bin/env python3
"""Test full googleapiclient stack with IPv4 patch."""
import os
import sys

# Ensure patch is applied BEFORE importing googleapiclient
sys.path.insert(0, '.')
import ipv4_google  # noqa: F401
print(f"Patch active: {getattr(ipv4_google.getaddrinfo_ipv4_first, '_ipv4_patched', False)}")

# Now test googleapiclient
try:
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials
    from youtube_oauth import TOKEN_PATH
    
    print("Building YouTube service...")
    y = build("youtube", "v3", credentials=Credentials.from_authorized_user_file(str(TOKEN_PATH)))
    
    print("Calling channels().list()...")
    ch = y.channels().list(part="contentDetails", mine=True).execute()
    print(f"SUCCESS: Got channel info, items={len(ch.get('items', []))}")
    
except Exception as e:
    print(f"FAILED: {type(e).__name__}: {e}")
    sys.exit(1)

print("All googleapiclient tests passed!")