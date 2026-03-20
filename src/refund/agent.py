from __future__ import annotations

from rich.console import Console

from src.browser.connection import BrowserManager
from src.browser.stealth import random_delay
from src.db.models import RefundRequest
from src.llm.client import LLMClient, ModelTier
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

        log.state = RefundState.NAVIGATING
        owned_page = False

        try:
            # First, try to find an already-open chat popup
            console.print("Looking for an open chat window...")
            nav_result, chat_ctx = self.navigator.find_open_chat(
                self.browser._require_browser()
            )

            if nav_result != NavResult.SUCCESS or chat_ctx is None:
                # Fallback: open a new page and navigate automatically
                console.print(
                    f"No open chat found. Navigating to CS for order {order_id}..."
                )
                page = self.browser.new_page()
                owned_page = True
                nav_result, chat_ctx = self.navigator.navigate_to_chat(
                    page, order_id, item_title=item_title
                )

            if nav_result != NavResult.SUCCESS or chat_ctx is None:
                log.state = RefundState.FAILED
                log.failure_reason = f"Navigation: {nav_result.name}"
                console.print(f"[red]Navigation failed: {nav_result.name}[/red]")
                return log

            console.print("[green]Chat window found![/green]")

            if dry_run:
                log.state = RefundState.OPENING
                console.print(
                    "[yellow]Dry run — chat window located. No messages sent.[/yellow]"
                )
                return log

            driver = ChatDriver(chat_ctx)

            # Read agent greeting (may already be present or arrive soon)
            greeting = driver.get_initial_greeting(timeout_sec=60)
            if greeting:
                log.add("agent", greeting)
                console.print(f"[green]<<< {greeting}[/green]")

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

                # ---- Terminal states ----
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
                    # Agent transferred — keep waiting
                    random_delay(1, 2)
                    continue

                # ---- Need to reply ----
                # Immediately show typing indicator so the agent sees "..."
                driver.start_typing()

                if new_state == RefundState.ESCALATING:
                    reply = ESCALATION_TEMPLATE
                else:
                    reply = self._llm_reply(system_prompt, log)

                # Clear indicator then send the real message
                driver.stop_typing()
                driver.send_message(reply)
                log.add("customer", reply)
                console.print(f"[blue]>>> {reply}[/blue]")
                random_delay(0.5, 1.0)

            if not dry_run and not log.is_terminal:
                log.state = RefundState.TIMEOUT
                log.failure_reason = f"Max rounds exceeded ({log.rounds})"

            return log
        finally:
            if owned_page:
                try:
                    page.close()
                except Exception:
                    pass

    def close(self) -> None:
        if self.llm is not None:
            self.llm.close()
            self.llm = None

    def _llm_reply(self, system_prompt: str, log: ConversationLog) -> str:
        """Generate the customer's next message using the LLM.

        Uses the **fast** tier for low-latency replies during live chat.
        Multi-turn history is packed into a single user message (transcript
        format) because the fast tier models may not preserve assistant-role
        context perfectly across providers.
        """
        if self.llm is None:
            self.llm = LLMClient(tier=ModelTier.FAST)

        # Pack conversation into transcript format for reliability.
        transcript_lines = []
        for entry in log.messages:
            label = "Agent" if entry["role"] == "agent" else "Customer"
            transcript_lines.append(f"{label}: {entry['content']}")
        transcript = "\n".join(transcript_lines)

        packed_prompt = (
            f"Here is the conversation so far:\n\n"
            f"{transcript}\n\n"
            f"Generate the customer's next message. "
            f"Keep it short (1-3 sentences), natural, polite, "
            f"and focused on getting the price adjustment."
        )

        return self.llm.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": packed_prompt},
            ],
        )
