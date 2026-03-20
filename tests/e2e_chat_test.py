#!/usr/bin/env python3
"""End-to-end chat test — validates the full pipeline.

This script:
1. Connects to Chrome via CDP
2. Optionally scrapes 2 recent orders (DOM selector validation)
3. Navigates to CS chat for a specific order (with item_title matching)
4. Handles "continue previous chat" dialog
5. Exchanges messages with the agent, measuring latency at every step

Usage:
    source .venv/bin/activate
    python tests/e2e_chat_test.py [--skip-collect] [--max-rounds 4]
    python tests/e2e_chat_test.py --asin B0FLQQDQH1 --max-rounds 3
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

sys.path.insert(0, ".")

# Enable debug logging for chat driver to see ghost row HTML
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler()],
)
logging.getLogger("ar.chat_driver").setLevel(logging.DEBUG)
logging.getLogger("ar.navigator").setLevel(logging.DEBUG)

from rich.console import Console
from rich.table import Table

console = Console()


def timed(label: str):
    """Context manager that prints elapsed time."""
    class _Timer:
        def __init__(self):
            self.elapsed = 0.0
        def __enter__(self):
            self._start = time.monotonic()
            return self
        def __exit__(self, *_):
            self.elapsed = time.monotonic() - self._start
            console.print(f"  ⏱  {label}: [cyan]{self.elapsed:.1f}s[/cyan]")
    return _Timer()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-collect", action="store_true",
                        help="Skip order collection, go straight to chat")
    parser.add_argument("--max-rounds", type=int, default=20,
                        help="Safety limit (default 20, not a hard cutoff)")
    parser.add_argument("--tier", default="fast",
                        choices=["thinking", "balanced", "fast"],
                        help="LLM tier for generating replies")
    parser.add_argument("--asin", default=None,
                        help="ASIN to use for the refund test")
    parser.add_argument("--dry-run", action="store_true",
                        help="Navigate to chat but don't send messages")
    args = parser.parse_args()

    console.rule("[bold]E2E Chat Flow Test[/bold]")

    # ── Step 0: Environment checks ────────────────────────────────────
    from src.browser.connection import BrowserManager
    from src.llm.client import LLMClient, ModelTier
    from src.db.connection import db
    from src.db.repository import OrderRepository, PriceRepository

    browser = BrowserManager()
    with timed("CDP connect") as t:
        browser.connect()
    console.print("[green]✓ Chrome connected[/green]")

    llm = LLMClient(tier=args.tier)
    with timed("LLM health") as t:
        healthy = llm.health_check()
    if not healthy:
        console.print("[red]✗ LLM service offline[/red]")
        return 1
    console.print(f"[green]✓ LLM service online, model={llm.model}[/green]")

    # ── Step 1: Find the target item ──────────────────────────────────
    console.rule("Step 1: Target Item")
    db.init_pool()

    target_asin = args.asin or "B0FLQQDQH1"
    target_item = None
    current_price = None

    try:
        with db.connection() as conn:
            repo = OrderRepository()
            items = repo.list_items(conn, asin=target_asin)
            if items:
                target_item = items[0]

            # Get current price
            price_repo = PriceRepository()
            prices = price_repo.list_latest_item_prices(conn)
            for p in prices:
                if p.item.asin == target_asin:
                    current_price = p.current_price
                    break
    finally:
        db.close()

    if target_item is None:
        console.print(f"[red]✗ ASIN {target_asin} not found in DB[/red]")
        return 1

    price_diff = target_item.purchase_price - (current_price or target_item.purchase_price)
    console.print(f"[green]✓ Target: {target_item.title[:60]}[/green]")
    console.print(f"  Order: {target_item.order_id}")
    console.print(f"  ASIN:  {target_asin}")
    console.print(f"  Price: ${target_item.purchase_price:.2f} → ${current_price:.2f} (drop ${price_diff:.2f})" if current_price else f"  Price: ${target_item.purchase_price:.2f}")

    # ── Step 1b: Optional order collection test ───────────────────────
    if not args.skip_collect:
        console.rule("Step 1b: Order Collection (DOM selectors)")
        from src.collector.order_scraper import OrderScraper

        scraper = OrderScraper(browser)
        with timed("Scrape 1 page of orders") as t:
            orders = scraper.scrape_orders(days=30)

        if orders:
            console.print(f"[green]✓ Found {len(orders)} orders[/green]")
            table = Table(title="Recent Orders (first 3)")
            table.add_column("Order ID")
            table.add_column("Date")
            table.add_column("Total")
            for o in orders[:3]:
                table.add_row(o.order_id, str(o.order_date), f"${o.total_amount:.2f}")
            console.print(table)
        else:
            console.print("[yellow]⚠ No orders found[/yellow]")

    # ── Step 2: Navigate to chat ──────────────────────────────────────
    console.rule("Step 2: Navigate to Chat")
    from src.refund.navigator import CustomerServiceNavigator, NavResult

    nav = CustomerServiceNavigator()

    # Always navigate fresh — each product needs its own chat session.
    # Close any existing chat popups first.
    console.print("Opening fresh chat for this product...")
    page = browser.new_page()
    with timed("Auto-navigate to CS chat") as t:
        result, chat_ctx = nav.navigate_to_chat(
            page, target_item.order_id,
            item_title=target_item.title
        )

    if result != NavResult.SUCCESS or chat_ctx is None:
        console.print(f"[red]✗ Navigation failed: {result.name}[/red]")
        browser.close()
        return 1

    console.print(f"[green]✓ Chat opened! URL: {chat_ctx.page.url[:80]}[/green]")

    if args.dry_run:
        console.print("[yellow]Dry run — stopping before sending messages.[/yellow]")
        browser.close()
        return 0

    # ── Step 3: Chat conversation ─────────────────────────────────────
    console.rule("Step 3: Live Chat")
    from src.refund.chat_driver import ChatDriver
    from src.browser.stealth import random_delay

    driver = ChatDriver(chat_ctx)

    # Wait for agent greeting
    console.print("Waiting for agent greeting...")
    with timed("Agent greeting") as t:
        greeting = driver.get_initial_greeting(timeout_sec=90)

    if greeting:
        console.print(f"[green]<<< {greeting}[/green]")
    else:
        console.print("[yellow]⚠ No greeting received (continuing anyway)[/yellow]")

    # Build opening message — real refund scenario
    if current_price and price_diff > 1:
        opening = (
            f"Hi! I recently purchased \"{target_item.title[:50]}\" "
            f"(order {target_item.order_id}) for ${target_item.purchase_price:.2f}, "
            f"but I noticed the price has dropped to ${current_price:.2f}. "
            f"Would it be possible to get a price adjustment of ${price_diff:.2f}? "
            f"Thank you!"
        )
    else:
        opening = (
            f"Hi! I have a question about my recent order {target_item.order_id} "
            f"for \"{target_item.title[:50]}\". "
            f"I was wondering if there are any promotions or price adjustments "
            f"available for this item. Thanks!"
        )

    console.print(f"\n[bold blue]>>> Sending opening message...[/bold blue]")
    with timed("Send opening") as t:
        driver.send_message(opening)
    console.print(f"[blue]>>> {opening}[/blue]")

    # Main chat loop
    round_timings = []
    transcript = [f"Customer: {opening}"]

    round_num = 0

    while round_num < args.max_rounds:
        round_num += 1
        console.print(f"\n[bold]─── Round {round_num} ───[/bold]")

        # Wait for agent reply
        with timed("Wait for agent reply") as t:
            agent_reply = driver.wait_for_agent_reply(timeout_sec=120)

        if agent_reply is None:
            if driver.is_chat_ended():
                console.print("[yellow]Chat ended by agent.[/yellow]")
            else:
                console.print("[red]Timeout waiting for agent reply.[/red]")
            break

        console.print(f"[green]<<< {agent_reply}[/green]")
        round_timings.append({"phase": f"R{round_num} agent_reply", "sec": t.elapsed})
        transcript.append(f"Agent: {agent_reply}")

        # Check if agent is still working ("let me check", "one moment", etc.)
        # If so, don't respond yet — wait for their follow-up
        if driver.agent_still_working(agent_reply):
            console.print("[yellow]⏳ Agent still working, waiting for follow-up...[/yellow]")
            continue  # go back to waiting for next agent message

        # Generate reply via LLM — let it decide what to say
        # (including farewell if the conversation is naturally ending)
        driver.start_typing()

        prompt = (
            f"Here is the conversation so far:\n\n"
            + "\n".join(transcript) + "\n\n"
            f"Generate the customer's next message. "
            f"The customer wants a price adjustment of ${price_diff:.2f} "
            f"(bought at ${target_item.purchase_price:.2f}, now ${current_price:.2f}). "
            f"Be polite, brief (1-3 sentences), and natural. "
            f"If the agent offers a credit or refund, accept it graciously and say goodbye. "
            f"If the agent clearly says they can't help and ends the conversation, "
            f"say thank you and goodbye. "
            f"If the agent says they can't help but seems open, politely ask "
            f"about promotional credits one more time."
        )

        system = (
            "You are a polite Amazon customer chatting with customer service. "
            "You want a price adjustment but you are not aggressive. "
            "Keep responses short and natural (1-3 sentences). "
            "When the issue is resolved (credit given, or agent clearly can't help), "
            "say thank you and end the conversation naturally."
        )

        with timed(f"LLM generate (tier={args.tier})") as t:
            customer_reply = llm.chat([
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ])
        round_timings.append({"phase": f"R{round_num} llm_gen", "sec": t.elapsed})

        driver.stop_typing()

        console.print(f"[blue]>>> {customer_reply}[/blue]")
        with timed("Send reply") as t:
            driver.send_message(customer_reply)
        transcript.append(f"Customer: {customer_reply}")
        random_delay(0.5, 1.0)

        # Check if the customer just said goodbye
        reply_lower = customer_reply.lower()
        if any(phrase in reply_lower for phrase in (
            "have a great day", "goodbye", "bye", "take care",
            "thanks for your help", "thank you for your help",
            "appreciate your help",
        )):
            console.print("[cyan]Customer said goodbye — ending chat.[/cyan]")
            break

    # ── Summary ───────────────────────────────────────────────────────
    console.rule("[bold]Timing Summary[/bold]")
    table = Table()
    table.add_column("Phase")
    table.add_column("Time (s)", justify="right")
    for entry in round_timings:
        color = "green" if entry["sec"] < 5 else "yellow" if entry["sec"] < 15 else "red"
        table.add_row(entry["phase"], f"[{color}]{entry['sec']:.1f}[/{color}]")
    console.print(table)

    if round_timings:
        avg = sum(e["sec"] for e in round_timings) / len(round_timings)
        console.print(f"\nAverage: [cyan]{avg:.1f}s[/cyan]")

    console.rule("[bold]Full Transcript[/bold]")
    for line in transcript:
        color = "blue" if line.startswith("Customer:") else "green"
        console.print(f"[{color}]{line}[/{color}]")

    # Cleanup
    llm.close()
    browser.close()
    console.print("\n[green]✓ E2E test complete![/green]")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
