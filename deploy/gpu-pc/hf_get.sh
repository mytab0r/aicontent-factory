#!/bin/sh
# hf_get.sh <url> <out> [extra curl args, e.g. -H "Authorization: Bearer $TOK"]
# Root cause t_5dccab9e: HF CDN (xet/CloudFront) closes ANY single HTTPS connection after ~205 s,
# regardless of speed (measured 22.10: 2.16 GB @10.5 MB/s and 0.65 GB @3 MB/s both cut with
# "SSL_read: unexpected eof" at ~207 s). One curl per multi-GB file can never finish.
# So download in byte ranges, each request well below that lifetime. No retries: a failed range
# fails loudly with curl rc + offset; the next run continues from the verified .part size.
set -eu
url=$1; out=$2; shift 2
chunk=${HF_CHUNK_BYTES:-268435456}        # 256 MiB: ~25 s @10 MB/s, still <180 s @1.5 MB/s
tmo=${HF_CHUNK_TIMEOUT:-180}              # below the ~205 s CDN connection lifetime
total=$(curl -fsSL -r 0-0 -o /dev/null -D - "$@" "$url" | tr -d '\r' \
  | sed -n 's#^[Cc]ontent-[Rr]ange: bytes 0-0/\([0-9][0-9]*\)$#\1#p' | tail -1)
[ -n "$total" ] || { echo "::error::hf_get: no Content-Range (HTTP error or no range support) $url" >&2; exit 1; }
if [ -f "$out" ] && [ "$(wc -c < "$out")" -eq "$total" ]; then echo "EXISTS $out"; exit 0; fi
have=0; [ -f "$out.part" ] && have=$(wc -c < "$out.part")
while [ "$have" -lt "$total" ]; do
  end=$((have + chunk - 1)); [ "$end" -lt "$total" ] || end=$((total - 1))
  rc=0; curl -fsSL -m "$tmo" -r "$have-$end" -o "$out.chunk" "$@" "$url" || rc=$?
  got=0; [ -f "$out.chunk" ] && got=$(wc -c < "$out.chunk")
  if [ "$rc" != 0 ] || [ "$got" -ne $((end - have + 1)) ]; then
    rm -f "$out.chunk"
    echo "::error::hf_get: range $have-$end/$total failed (curl rc=$rc, got $got bytes) $url" >&2; exit 1
  fi
  cat "$out.chunk" >> "$out.part"; rm -f "$out.chunk"
  have=$((end + 1))
done
mv "$out.part" "$out"
echo "OK $out ($total bytes)"
