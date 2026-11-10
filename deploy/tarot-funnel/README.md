# tarot-funnel — Landing Page for Tarot Offer

## Overview
Landing page for the tarot funnel: free first reading via ManyChat (IG/TikTok DM) → USDT payment for subscriptions on pay.pxbt.app.

## Architecture
- **Frontend**: Single-page HTML (`index.html`) with vanilla JS, QR code generation via qrcode-generator CDN
- **Backend**: Node.js stdlib only (`server.js`), no npm dependencies
- **Integration**: Calls `pay.pxbt.app/api/invoice` for wallet verification and invoice creation
- **ManyChat**: Redirects to `m.me/<PAGE_ID>?ref=<wallet_ref>` after verification

## Environment Variables
| Variable | Required | Description |
|----------|----------|-------------|
| `PORT` | No | Server port (default: 8081) |
| `DATA_DIR` | No | Data directory for KV storage (default: /data) |
| `MANYCHAT_PAGE_ID` | Yes | ManyChat Facebook page ID for m.me links |
| `MANYCHAT_TOKEN` | No | ManyChat API token (for future webhook integration) |
| `PAY_API_TOKEN` | Yes | Bearer token for pay.pxbt.app API calls |

## API Endpoints

### GET /
Serves the landing page HTML.

### GET /healthz
Health check endpoint.

### POST /api/tarot/verify
Verify wallet and get ManyChat redirect URL.
```json
// Request
{ "wallet": "T... | 0x... | <solana>" }

// Response (success)
{ "ok": true, "manychat_url": "https://m.me/<PAGE_ID>?ref=tarot_...", "message": "..." }

// Response (error)
{ "error": "..." }
```

### GET /api/tarot/addresses
Proxy to pay.pxbt.app/api/address for payment QR codes.
```json
// Response
{ "tron": "T...", "evm": "0x...", "solana": "..." }
```

### POST /api/tarot/subscribe
Create paid subscription invoice (requires PAY_API_TOKEN).
```json
// Request
{ "wallet": "...", "tier": "basic|unlimited" }

// Response
{ "id": "...", "url": "/i/...", "amount": "15.000001" }
```

### POST /api/tarot/manychat-callback
Webhook for ManyChat flow completion (future use).

## Deployment

### Docker (Production)
```bash
cd deploy/tarot-funnel
docker compose up -d
```

Required `.env` file:
```
PORT=8081
DATA_DIR=/data
MANYCHAT_PAGE_ID=your_page_id
MANYCHAT_TOKEN=your_token
PAY_API_TOKEN=your_pay_api_token
```

### GitHub Actions CI/CD
Workflow: `.github/workflows/tarot-funnel-image.yml`
- Triggers on successful `ci` workflow completion on master/main
- Builds and pushes to `ghcr.io/mytab0r/tarot-funnel:latest`
- Watchtower on VPS auto-updates

### VPS Deployment (Watchtower)
Add to VPS docker-compose.yml:
```yaml
services:
  tarot-funnel:
    image: ghcr.io/mytab0r/tarot-funnel:latest
    restart: unless-stopped
    env_file: .env.tarot-funnel
    volumes:
      - ./data/tarot-funnel:/data
    ports:
      - "127.0.0.1:8081:8081"
    labels:
      com.centurylinklabs.watchtower.enable: "true"
```

## Free Tier Logic
1. User enters USDT wallet address on landing page
2. Server validates format (TRC20/ERC20/Solana)
3. Checks `tarot-used-wallets.json` for previous use (30-day expiry)
4. Calls `pay.pxbt.app/api/invoice` with `tier: free_tarot, amount: 0`
5. On success: marks wallet used, generates ManyChat ref URL, redirects
6. ManyChat flow delivers first free reading

## Paid Tiers
| Tier | Price | Description |
|------|-------|-------------|
| Basic | 15 USDT/month | 3 readings/day |
| Unlimited | 45 USDT/month | Unlimited readings |

## Security
- Wallet validation prevents fake addresses
- 30-day cooldown per wallet for free tier
- PAY_API_TOKEN required for paid invoice creation
- CORS enabled for landing page calls
- No sensitive data logged

## Monitoring
- Health check: `GET /healthz`
- Logs: `docker logs tarot-funnel`
- Watchtower auto-updates on new GHCR image
