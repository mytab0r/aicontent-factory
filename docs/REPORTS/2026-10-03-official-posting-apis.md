# Official posting APIs: TikTok / Instagram Reels / YouTube Shorts (2026)

Researcher: subagent (auto-worker-combo), 2026-10-03. All gating rules verified
against primary platform docs. Sources: 37-item ledger at
`/opt/data/cache/citations/ledger.json` (written by the research subagent; key
sources mirrored in the Sources section below).

## Verdict per platform

**YouTube Shorts — ✅ fully automatable today, $0, no review for own channel.**
- Official Data API v3 `videos.insert`, resumable upload; Shorts are just
  vertical uploads [6]
- No app review to post to your own channel. One trap: `youtube.upload` is a
  sensitive scope — app left in "Testing" = refresh tokens expire after 7 days
  (breaks unattended cron); fix is moving to production/verification, or
  staying testing-only with weekly manual re-consent [12]
- Quota: default 10k units/day; uploads are the expensive call (1600 units
  classic accounting, docs also now describe a 100 calls/day insert bucket) —
  comfortably enough for lofi cadence [6][8]
- More quota: manual audit form only, weeks-to-months, **cannot pay** — no
  paid tier [7]
- Unattended: one-time human OAuth consent, then refresh forever; native
  `publishAt` scheduling in upload body [14]. Post-2020 API projects need a
  free project-level audit form to lift private-only lock on uploads — file it
  early [6]

**Instagram Reels — ✅ official Graph API, and the key finding: no app review
needed for own accounts.**
- Meta's own review matrix: "My app is only for a business I own or manage" →
  Standard Access → **App Review not required**; review + business verification
  only for Advanced Access (serving accounts you don't own) [10][11]
- Account must be professional (Business/Creator) [5]. Flow:
  `/{ig-id}/media` container → poll `status_code` → `media_publish` [4]
- Auth: 1h token → 60-day long-lived token, refreshable via endpoint — solved
  cron refresh [16]
- Publishing quota: per-account rolling 24h; docs contradict themselves (guide
  says 100, reference says 50) — trust the live `content_publishing_limit`
  endpoint; both far above lofi volume [4][35]. Containers expire after 24h
  unpublished
- Cost $0, ~1 day setup. Review only triggers if you ever post to accounts you
  don't own.

**TikTok — ⚠️ official API exists; public unattended posting gated behind
manual audit.**
- Direct Post (`video.publish`) vs Upload-to-inbox (`video.upload`) [3][15]
- Unaudited clients: forced `SELF_ONLY` (private), account must be private,
  max **5 users/24h**; everyone: ~15 posts/day/creator cap, per-app creator
  cap [2][15]. Inbox mode is not publication — human finishes in-app =
  human-in-the-loop, not automation
- Public automated posting = pass the Content Posting API audit: production
  app, verified domains, HTTPS legal pages, 3–5 min demo screencast, mandated
  consent UX; TikTok quotes days-to-2-weeks, practitioners report ~6 weeks and
  multiple submissions; approval discretionary [15][34]. Audit UX requirements
  assume a human pressing "post" — headless scheduler is in tension with
  "users must have full awareness and control" [2]. Realistic small-creator
  outcome: semi-manual (inbox draft) or parallel audit application
- Registration: individual dev account OK; URL verification required; no fee
  [13]

**Ruled out (ToS-violating, per owner constraint):**
- Reverse-engineered private APIs (`tiktok-private-api` etc.) — own docs admit
  ToS violation; signature/TLS-fingerprint bans, CFAA-adjacent unauthorized
  access, constant breakage [36][37]
- Real-device-farm/account-pool services (TokPortal-style) — evades fraud
  detection by design, same ToS breach, credential handover to third party
  [36]
- Browser/UI automation on the upload pages — not an API, violates terms,
  brittle
- Credential-sharing through someone's audited client — violates TikTok
  credential-confidentiality rules [2]

**Aggregator fallback:** Ayrshare-type unified APIs (own audited apps,
official under the hood): $149/mo Premium (1 profile/14 networks) [17];
Blotato cheaper (~$29–49/mo). Worth it if TikTok audit fails or maintenance
exceeds tolerance.

## Recommended shape

| Platform | Route | Human steps | Cost |
|---|---|---|---|
| YouTube Shorts | `videos.insert` | one-time OAuth; file project audit form | $0 |
| IG Reels | container→publish + token refresh cron | one-time OAuth | $0 |
| TikTok | inbox-draft now; Direct Post audit in parallel | 1-tap inbox publish (or none if audited) | $0 |

## Sources (mirrored from subagent ledger)

- [2] https://developers.tiktok.com/doc/content-sharing-guidelines
- [3] https://developers.tiktok.com/doc/content-posting-api-get-started
- [4] https://developers.facebook.com/documentation/instagram-platform/content-publishing
- [5] https://developers.facebook.com/documentation/instagram-platform/overview
- [6] https://developers.google.com/youtube/v3/docs/videos/insert
- [7] YouTube API quota increase / audit form (developer docs)
- [8] YouTube Data API quota calculator (developer docs)
- [10] Meta app review matrix (developers.facebook.com)
- [11] Meta Standard vs Advanced Access (developers.facebook.com)
- [12] Google OAuth sensitive scopes / testing-mode token expiry
- [13] TikTok developer registration
- [14] YouTube `publishAt` scheduling docs
- [15] TikTok Content Posting API audit requirements
- [16] Meta long-lived tokens docs
- [17] Ayrshare pricing
- [34] TikTok audit timeline practitioner reports
- [35] IG `content_publishing_limit` endpoint
- [36] tiktok-private-api / device-farm services analysis
- [37] TikTok ToS / API terms

Full ledger with access dates: `/opt/data/cache/citations/ledger.json`
(subagent session artifact — copy key URLs into this file if it gets pruned).
