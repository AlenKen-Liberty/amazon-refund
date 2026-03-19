# Amazon Refund

Phase 1 MVP for collecting Amazon orders, checking current prices, and identifying price drops from the CLI.

## Requirements

- Python 3.11
- A Chromium browser started with CDP enabled
- Oracle DB credentials in `.env`

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

## Commands

```bash
ar init-db
ar collect --days 90
ar check
ar analyze
ar refund --dry-run --limit 1
ar test-llm
```

## Launch Chrome

```bash
./scripts/launch_chrome.sh
```
