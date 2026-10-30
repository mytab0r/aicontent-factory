#!/bin/sh
export AUTOSSH_GATETIME=0 AUTOSSH_POLL=30
cp /k/key2 /tmp/key && chmod 600 /tmp/key
exec autossh -M 0 -N -i /tmp/key -p 22 -o UserKnownHostsFile=/k/known_hosts -o StrictHostKeyChecking=yes -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o ConnectTimeout=10 \
  -R 127.0.0.1:2223:hermes-runner:22 \
  -R 127.0.0.1:9222:runner-browser:9222 \
  -R 127.0.0.1:2376:auth-proxy:80 \
  -R 127.0.0.1:3030:langfuse-web:3000 \
  pclink@167.99.134.201