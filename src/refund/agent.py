from __future__ import annotations

from rich.console import Console

from src.browser.connection import BrowserManager
from src.browser.stealth import random_delay
from src.db.models import RefundRequest
from src.llm.client import LLMClient
from src.refund.chat_driver import ChatDriver
from src.refund.navigator import CustomerServiceNavigator, NavResult
from src.refund.prompts import (
    ACCEPT_CREDIT_TEMPLATE,
    CLOSING_TEMPLATE,
    ESCALATION_TEMPLATE,
    build_opening_message,
    build_system_prompt,
)
from src.refund.safety import SafetyGuard
from src.refund.strategy import ConversationLog, OutcomeDetector, RefundState

console = Console()


class RefundAgent:
    def __init__(self, browser: BrowserManager) -> None:
        self.browser = browser
        self.navigator = CustomerServiceNavigator()
        self.detector = OutcomeDetector()
        self.safety = SafetyGuard()
        self.llm: LLMClient | None = None

    def process_request(
        self,
        request: RefundRequest,
        *,
        order_id: str,
        item_title: str,
        purchase_date: str,
        dry_run: bool = False,
    ) -> ConversationLog:
        log = ConversationLog()
        can_proceed, reason = self.safety.can_proceed()
        if not can_proceed:
            log.state = RefundState.FAILED
            log.failure_reason = f"Safety: {reason}"
            console.print(f"[red]Safety block: {reason}[/red]")
            return log

        page = self.browser.new_page()
        log.state = RefundState.NAVIGATING

        try:
            console.print(f"Navigating to CS chat for order {order_id}...")
            nav_result, chat_ctx = self.navigator.navigate_to_chat(page, order_id)
            if nav_result != NavResult.SUCCESS or chat_ctx is None:
                log.state = RefundState.FAILED
                log.failure_reason = f"Navigation: {nav_result.name}"
                console.print(f"[red]Navigation failed: {nav_result.name}[/red]")
                return log

            if dry_run:
                log.state = RefundState.OPENING
                console.print(
                    "[yellow]Dry run reached the chat window. No messages were sent.[/yellow]"
                )
                return log

            driver = ChatDriver(chat_ctx)
            opening = build_opening_message(
                order_id,
                item_title,
                request.purchase_price,
                request.current_price,
                request.price_diff,
            )
            driver.send_message(opening)
            log.add("customer", opening)
            log.state = RefundState.OPENING
            console.print(f"[blue]>>> {opening}[/blue]")

            system_prompt = build_system_prompt(
                order_id,
                item_title,
                purchase_date,
                request.purchase_price,
                request.current_price,
                request.price_diff,
            )

            while log.should_continue:
                prior_state = log.state
                log.state = RefundState.WAITING_REPLY
                agent_reply = driver.wait_for_agent_reply(timeout_sec=90)

                if agent_reply is None:
                    if driver.is_chat_ended():
                        log.state = RefundState.FAILED
                        log.failure_reason = "Chat ended by agent"
                    else:
                        log.state = RefundState.TIMEOUT
                        log.failure_reason = "Agent reply timeout"
                    break

                log.add("agent", agent_reply)
                console.print(f"[green]<<< {agent_reply}[/green]")

                new_state = self.detector.detect(agent_reply, prior_state)
                log.state = new_state

                if new_state == RefundState.COMPLETED:
                    log.refund_amount = self.detector.extract_refund_amount(agent_reply)
                    log.refund_type = self.detector.extract_refund_type(agent_reply)
                    driver.send_message(ACCEPT_CREDIT_TEMPLATE)
                    log.add("customer", ACCEPT_CREDIT_TEMPLATE)
                    console.print(
                        f"[bold green]Refund obtained: ${log.refund_amount or 0:.2f}[/bold green]"
                    )
                    break

                if new_state == RefundState.SAFETY_STOP:
                    log.failure_reason = "Safety signal in agent reply"
                    console.print(
                        "[bold red]Safety signal detected. Stopping.[/bold red]"
                    )
                    break

                if new_state == RefundState.FAILED:
                    driver.send_message(CLOSING_TEMPLATE)
                    log.add("customer", CLOSING_TEMPLATE)
                    log.failure_reason = "Refund rejected after escalation"
                    break

                if new_state == RefundState.WAITING_REPLY:
                    random_delay(1, 2)
                    continue

                if new_state == RefundState.ESCALATING:
                    reply = ESCALATION_TEMPLATE
                else:
                    reply = self._llm_reply(system_prompt, log)

                driver.send_message(reply)
                log.add("customer", reply)
                console.print(f"[blue]>>> {reply}[/blue]")
                random_delay(1, 2)

            if not dry_run and not log.is_terminal:
                log.state = RefundState.TIMEOUT
                log.failure_reason = f"Max rounds exceeded ({log.rounds})"

            return log
        finally:
            page.close()

    def close(self) -> None:
        if self.llm is not None:
            self.llm.close()
            self.llm = None

    def _llm_reply(self, system_prompt: str, log: ConversationLog) -> str:
        if self.llm is None:
            self.llm = LLMClient()

        messages = [{"role": "system", "content": system_prompt}]
        for message in log.messages:
            role = "assistant" if message["role"] == "agent" else "user"
            messages.append({"role": role, "content": message["content"]})
        messages.append(
            {
                "role": "user",
                "content": (
                    "Generate the customer's next message. Keep it short, natural, and focused "
                    "on getting the refund."
                ),
            }
        )
        return self.llm.chat(messages, temperature=0.7, max_tokens=200)
