# Amazon Refund

Amazon order monitoring and refund-chat automation for price drops.

The project connects to your already logged-in Chrome session through CDP, stores order and price state in a configurable database backend, and uses a configurable OpenAI-compatible LLM endpoint to generate customer-service replies.

## What You Can Do With It

- Validate your LLM setup immediately after cloning
- Collect orders from Amazon order history
- Re-check live product prices with multiple extraction strategies
- Detect meaningful price drops and queue refund candidates
- Open Amazon customer service chat and negotiate a refund or credit

## Quick Start: LLM Smoke Test

If you only want to confirm that the project can talk to your model, you only need Python and an OpenAI-compatible LLM endpoint.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Set these values in `.env`:

```bash
AR_LLM_BASE_URL=http://127.0.0.1:7860
AR_LLM_MODEL=codex
```

Then run:

```bash
ar test-llm --message "Say hello in one sentence."
```

That command exercises the same OpenAI-compatible chat path used by the refund agent.

## Full Automation Requirements

For the full Amazon workflow you also need:

- Python 3.11
- Chromium or Chrome running with CDP on port `9222`
- An Amazon account already signed in inside that browser
- A database backend configured in `.env`

## Installation

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

## Configuration

### Required for LLM Chat

These settings drive the refund/chat agent and the `ar test-llm` command:

| Variable | Purpose |
| --- | --- |
| `AR_LLM_BASE_URL` | Base URL of your OpenAI-compatible endpoint |
| `AR_LLM_MODEL` | Model name to send in `/v1/chat/completions` |

Example:

```bash
AR_LLM_PROVIDER=openai_compatible
AR_LLM_BASE_URL=http://127.0.0.1:7860
AR_LLM_MODEL=codex
```

### Optional LLM Fallback for Price Extraction

`AR_LLM_PROVIDER` is also used by the price-extraction fallback in `src/monitor/extractors/llm.py`.

Supported values:

- `openai_compatible`
- `ollama`
- `openai`
- `anthropic`

If you use one of the non-default providers, also fill the matching settings in `.env.example`.

### Required for Order Collection, Price Checks, and Refund Runs

These settings are required for the database-backed workflow:

- `AR_DB_BACKEND`
- `AR_DB_USER`
- `AR_DB_PASSWORD`
- `AR_DB_DSN`
- `AR_DB_WALLET_DIR` and `AR_DB_WALLET_PASSWORD` only if your Oracle deployment needs a wallet

Current status:

- The repository ships with an Oracle implementation out of the box
- `AR_DB_BACKEND` makes the storage choice explicit in user config
- If you want Postgres, MySQL, SQLite, or another store, swap the `src/db/` implementation and keep `AR_DB_BACKEND` aligned with your adapter

### Required for Browser Automation

- `AR_CDP_PORT=9222` by default
- A logged-in Amazon session in the browser attached to that port

## Running Chrome With CDP

```bash
./scripts/launch_chrome.sh
```

The script starts Chrome with remote debugging enabled. Log into Amazon in that browser window before running `collect`, `check`, or `refund`.

## End-to-End Workflow

### 1. Initialize the database

```bash
ar init-db
```

### 2. Collect recent orders

```bash
ar collect --days 90
```

### 3. Check current prices

```bash
ar check
```

You can also limit the run to one product:

```bash
ar check --asin B0FLQQDQH1
```

### 4. Build refund candidates

```bash
ar analyze
```

### 5. Dry-run the refund flow

```bash
ar refund --dry-run --limit 1
```

This verifies that the tool can locate the customer-service chat window without sending a message.

### 6. Run a live refund attempt

```bash
ar refund --limit 1
```

## Core Commands

```bash
ar init-db
ar collect --days 90
ar check
ar analyze
ar refund --dry-run --limit 1
ar refund --limit 1
ar status
ar test-llm
```

## How The System Works

### Order collection

`src/collector/order_scraper.py` reads Amazon order-history cards, follows order-detail pages, and stores orders and purchased items in the configured backend.

### Price checking

`src/monitor/price_checker.py` combines four extractors:

- JSON-LD
- CSS selectors
- regex fallback
- LLM fallback

The final price is chosen by `src/monitor/voter.py`.

### Refund automation

`src/refund/navigator.py` navigates the Amazon customer-service flow, replays previously successful button paths first, and falls back to exploratory button scoring when the UI changes.

`src/refund/chat_driver.py` reads and sends chat messages inside the popup window, filters ghost rows, waits for multi-part agent replies to settle, and detects when the chat has ended.

`src/refund/agent.py` coordinates navigation, prompt building, reply generation, and safety limits.

## Local Runtime Files

The repository intentionally keeps local-only state out of Git:

- `.env`
- `doc/`
- `data/`
- `.claude/`
- `tests/debug_*.py`

In particular, `data/nav_paths.json` is treated as learned runtime state, not a public source file.

## Manual and Automated Tests

Run the regular non-manual suite:

```bash
pytest tests -v -m "not manual"
```

Run the focused LLM suite:

```bash
pytest tests/test_llm_client.py tests/test_llm_models.py -v
```

Run the manual refund flow checks:

```bash
pytest tests/e2e/test_refund_flow.py -v -s -m manual
python tests/e2e_chat_test.py --asin B0FLQQDQH1 --skip-collect --tier fast --max-rounds 5
```
