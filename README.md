# Jaringan Dagang - Seller Platform (BPP)

Beckn Provider Platform for Indonesia's open commerce network. This is the seller-side service that implements all 10 Beckn protocol endpoints.

## Features

- Full Beckn BPP with search, select, init, confirm, status, track, cancel, update, rating, support
- Product catalog management with PostgreSQL full-text search
- Xendit payment integration (QRIS, VA, e-wallets)
- Biteship shipping integration (all Indonesian couriers)
- TikTok Shop sync engine (marketplace adapter pattern)
- Seller dashboard REST API

## Quick Start

```bash
pip install -r requirements.txt
export DATABASE_URL="postgresql+asyncpg://jaringan:jaringan_dev@localhost:5433/jaringan_dagang"
uvicorn app.main:app --port 8001
python scripts/seed-matchamu.py  # Seed sample catalog
```

## Related Repos

- [jaringan-dagang-network](https://github.com/MetatechID/jaringan-dagang-network) - Network infrastructure
- [jaringan-dagang-buyer](https://github.com/MetatechID/jaringan-dagang-buyer) - BAP (Buyer platform)
