from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

from src.analyzer.price_drop import PriceDropAnalyzer
from src.browser.connection import BrowserManager
from src.collector.order_scraper import OrderScraper
from src.db.connection import db
from src.db.migrations import create_tables
from src.db.models import PriceRecord
from src.db.repository import (
    OrderRepository,
    PriceRepository,
    RefundRepository,
    SystemRepository,
)
from src.llm.client import LLMClient
from src.monitor.price_checker import PriceChecker
from src.refund.agent import RefundAgent
from src.refund.strategy import ConversationLog, RefundState

app = typer.Typer(
    help="Amazon price tracking and auto-refund CLI", no_args_is_help=True
)
console = Console()


@app.command()
def init_db() -> None:
    """Create Oracle tables and indexes."""
    db.init_pool()
    create_tables(db)
    db.close()
    console.print("[green]Database schema is ready.[/green]")


@app.command()
def collect(
    days: int = typer.Option(90, min=1, help="Collect orders from the last N days."),
) -> None:
    """Collect Amazon orders and items into Oracle DB."""
    repository = OrderRepository()
    browser = BrowserManager()

    db.init_pool()
    browser.connect()

    try:
        scraper = OrderScraper(browser)
        orders = scraper.scrape_orders(days=days)

        with db.connection() as connection:
            for order in orders:
                repository.upsert_order(connection, order)
                connection.commit()
                items = scraper.scrape_order_items(order.order_id)
                repository.upsert_items(connection, items)
                connection.commit()

        console.print(f"[green]Collected {len(orders)} orders.[/green]")
    finally:
        browser.close()
        db.close()


@app.command()
def check(
    asin: str | None = typer.Option(None, help="Only check a single ASIN."),
    limit: int | None = typer.Option(
        None, min=1, help="Limit the number of items checked."
    ),
) -> None:
    """Check the latest price for collected items."""
    order_repo = OrderRepository()
    price_repo = PriceRepository()
    browser = BrowserManager()

    db.init_pool()
    browser.connect()

    try:
        with db.connection() as connection:
            items = order_repo.list_items(connection, asin=asin, limit=limit)

        if not items:
            console.print("[yellow]No items found. Run `ar collect` first.[/yellow]")
            return

        checker = PriceChecker(browser)
        results = checker.check_items(items)

        with db.connection() as connection:
            for result in results:
                if result.final_price is None:
                    continue
                price_repo.record_price(
                    connection,
                    PriceRecord(
                        asin=result.item.asin,
                        price=result.final_price,
                        extraction_method=result.extraction_method or "unknown",
                    ),
                )
            connection.commit()

        table = Table(title="Price Check Results")
        table.add_column("ASIN")
        table.add_column("Order")
        table.add_column("Purchase")
        table.add_column("Current")
        table.add_column("Method")

        for result in results:
            table.add_row(
                result.item.asin,
                result.item.order_id,
                f"${result.item.purchase_price:.2f}",
                f"${result.final_price:.2f}"
                if result.final_price is not None
                else "N/A",
                result.extraction_method or "none",
            )

        console.print(table)
    finally:
        browser.close()
        db.close()


@app.command()
def analyze() -> None:
    """Analyze latest prices and create pending refund candidates."""
    analyzer = PriceDropAnalyzer()
    price_repo = PriceRepository()
    refund_repo = RefundRepository()

    db.init_pool()
    try:
        with db.connection() as connection:
            latest_prices = price_repo.list_latest_item_prices(connection)

            drops = []
            for snapshot in latest_prices:
                drop = analyzer.analyze(snapshot.item, snapshot.current_price)
                if drop:
                    drops.append(drop)

            refund_queue = analyzer.build_refund_queue(drops)
            refund_repo.upsert_pending_requests(connection, refund_queue)
            connection.commit()

        if not drops:
            console.print("[yellow]No qualifying price drops found.[/yellow]")
            return

        table = Table(title="Price Drops")
        table.add_column("Order")
        table.add_column("ASIN")
        table.add_column("Purchase")
        table.add_column("Current")
        table.add_column("Drop")
        table.add_column("% Drop")

        for drop in sorted(drops, key=lambda row: row.price_diff, reverse=True):
            table.add_row(
                drop.item.order_id,
                drop.item.asin,
                f"${drop.item.purchase_price:.2f}",
                f"${drop.current_price:.2f}",
                f"${drop.price_diff:.2f}",
                f"{drop.pct_drop:.1f}%",
            )
        console.print(table)
    finally:
        db.close()


@app.command()
def status() -> None:
    """Show database counters."""
    stats_repo = SystemRepository()

    db.init_pool()
    try:
        with db.connection() as connection:
            stats = stats_repo.get_stats(connection)
    finally:
        db.close()

    table = Table(title="System Status")
    table.add_column("Metric")
    table.add_column("Count")
    for key, value in stats.items():
        table.add_row(key, str(value))
    console.print(table)


@app.command()
def refund(
    order_id: str | None = typer.Argument(
        None, help="Process a specific order. Omit to process the queue."
    ),
    dry_run: bool = typer.Option(
        False, help="Navigate only and do not send chat messages."
    ),
    limit: int = typer.Option(5, min=1, help="Max requests to process from the queue."),
) -> None:
    """Execute AI-assisted refund conversations with Amazon customer service."""
    refund_repo = RefundRepository()
    pending_requests = []

    db.init_pool()
    try:
        with db.connection() as connection:
            pending_requests = refund_repo.list_pending(
                connection, limit=limit, order_id=order_id
            )
    finally:
        db.close()

    if not pending_requests:
        console.print("[yellow]No pending refund requests.[/yellow]")
        return

    if not dry_run:
        llm = LLMClient()
        try:
            if not llm.health_check():
                console.print("[red]Configured LLM service is not reachable.[/red]")
                raise typer.Exit(1)
        finally:
            llm.close()

    browser = BrowserManager()
    browser.connect()
    agent = RefundAgent(browser)
    db.init_pool()

    try:
        console.print(f"Found {len(pending_requests)} pending requests.")

        with db.connection() as connection:
            for request in pending_requests:
                details = refund_repo.get_item_details(connection, request.item_id)
                if not details:
                    console.print(
                        f"[yellow]Skipping missing item {request.item_id}.[/yellow]"
                    )
                    continue

                console.print(f"\n{'=' * 60}")
                console.print(f"Order: {details['order_id']} | {details['title'][:50]}")
                console.print(
                    f"Price drop: ${request.purchase_price:.2f} -> ${request.current_price:.2f} "
                    f"(-${request.price_diff:.2f})"
                )

                log = agent.process_request(
                    request,
                    order_id=details["order_id"],
                    item_title=details["title"],
                    purchase_date=details["purchase_date"],
                    dry_run=dry_run,
                )

                if dry_run:
                    if log.failure_reason:
                        console.print(f"[yellow]{log.failure_reason}[/yellow]")
                    continue

                if request.refund_id is None:
                    console.print(
                        f"[yellow]Skipping request without refund_id for item {request.item_id}.[/yellow]"
                    )
                    continue

                refund_repo.update_result(
                    connection,
                    request.refund_id,
                    status=_refund_status(log),
                    refund_amount=log.refund_amount,
                    refund_type=log.refund_type,
                    conversation_log=json.dumps(log.messages, ensure_ascii=False),
                    failure_reason=log.failure_reason,
                )
                connection.commit()

                console.print(
                    f"Result: {log.state.name} | Refund: ${log.refund_amount or 0:.2f}"
                )
    finally:
        agent.close()
        browser.close()
        db.close()


@app.command()
def test_llm(
    message: str = typer.Option(
        "Hello, can you help me?", help="Test message to send."
    ),
) -> None:
    """Verify LLM connectivity and print one response."""
    llm = LLMClient()
    try:
        if not llm.health_check():
            console.print("[red]Configured LLM service is offline.[/red]")
            raise typer.Exit(1)

        console.print(f"[green]LLM service online. Model: {llm.model}[/green]")
        console.print(f"Sending: {message}")
        reply = llm.chat([{"role": "user", "content": message}])
        console.print(f"[cyan]Reply: {reply}[/cyan]")
    finally:
        llm.close()


def _refund_status(log: ConversationLog) -> str:
    if log.state == RefundState.COMPLETED:
        return "completed"
    if log.state == RefundState.SAFETY_STOP:
        return "safety_stop"
    if log.state == RefundState.TIMEOUT:
        return "timeout"
    if log.state == RefundState.FAILED:
        return "failed"
    return log.state.name.lower()


if __name__ == "__main__":
    app()
