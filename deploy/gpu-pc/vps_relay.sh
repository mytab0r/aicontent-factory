#!/bin/sh
# R2 fallback: pull on VPS (30MB/s to GHCR), stream docker save over ssh, docker load on PC.
# Owner R3: single stream, temp only on C: (docker load streams, no temp), resume = rerun.
set -e
IMG=ghcr.io/ace-step/ace-step-1.5:latest
ssh vps "docker pull -q $IMG && docker save $IMG | gzip -1" | docker load
echo "relay load done"
