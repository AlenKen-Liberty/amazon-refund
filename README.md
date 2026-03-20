# Amazon Refund

Automated Amazon price-drop refund tool. Collects order history, monitors current prices, and negotiates refunds via live CS chat.

## Architecture

```
Phase 1: Data Collection          Phase 2: Automated Chat
┌──────────┐  ┌───────────┐      ┌───────────┐  ┌────────────┐
│  Order    │→ │  Price    │  →   │ Navigator │→ │ ChatDriver │
│ Scraper   │  │ Checker   │      │(2-phase)  │  │  + LLM     │
└──────────┘  └───────────┘      └───────────┘  └────────────┘
     ↓              ↓                  ↓               ↓
   Oracle DB    Price History    nav_paths.json   Chat Transcript
```

### Key Components

- **Navigator** (`src/refund/navigator.py`): Two-phase CS chat navigation
  - Phase 1: Replay known successful paths from `data/nav_paths.json`
  - Phase 2: Exploratory button scoring to discover new paths
  - Auto-detects dead ends (forms, phone-only) and backtracks
  - Persists successful paths for future use

- **ChatDriver** (`src/refund/chat_driver.py`): Message send/receive on CS chat popup
  - Ghost row filtering (icon-only renders)
  - Settle window for multi-part agent messages
  - Agent "still working" detection (e.g. "let me check")

- **LLM Client** (`src/llm/client.py`): Chat2API integration
  - Tiered models: thinking / balanced / fast
  - Packed transcript format for multi-turn context
  - Auto-degradation on backend errors

- **SmartSelector** (`src/browser/selectors.py`): Resilient DOM selectors
  - Multi-strategy chains (CSS, XPath, text)
  - Fallback progression for Amazon's varying DOM

## Requirements

- Python 3.11
- Chromium with CDP on port 9222
- Chat2API at `127.0.0.1:7860`
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
ar init-db          # Initialize database schema
ar collect --days 90 # Scrape order history
ar check            # Check current prices
ar analyze          # Find price drops
ar refund --dry-run --limit 1  # Test refund flow
ar test-llm         # Verify LLM connectivity
```

## E2E Testing

```bash
# Test full chat flow with a specific product
python tests/e2e_chat_test.py --asin B0FLQQDQH1 --skip-collect --tier fast --max-rounds 5
```

## Launch Chrome

```bash
./scripts/launch_chrome.sh
```

## Tests

```bash
pytest tests/ -v
```
