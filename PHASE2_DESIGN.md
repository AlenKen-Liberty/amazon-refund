# Phase 2 设计文档 — AI 客服退款 + 通知系统

> 基于 Phase 1 已实现的基础设施，设计 AI 退款对话和通知模块
> 日期：2026-03-18

---

## 一、Phase 1 回顾

**已完成：**
- CDP 浏览器连接（Patchright）
- 订单采集引擎（order_scraper）
- 4 路价格提取 + 投票器
- 降价分析 + 退款队列
- Oracle DB (OCI) 全套 CRUD
- CLI 命令：`init-db`, `collect`, `check`, `analyze`, `status`
- 端到端验证成功，已发现可退款商品

**Phase 2 目标：** 自动打开 Amazon 客服聊天，用 LLM 生成对话完成退款

---

## 二、LLM 引擎 — Chat2API

本地运行的 Chat2API 服务提供 OpenAI 兼容 API，无需额外 API Key。

| 配置项 | 值 |
|--------|-----|
| 服务地址 | `http://127.0.0.1:7860` |
| API 格式 | OpenAI `/v1/chat/completions` |
| 测试模型 | `codex`（别名 → `gpt-5.4`） |
| 备选模型 | `gemini`（别名 → `gemini-3.1-pro-preview`） |
| 认证 | 无需 API Key（本地服务） |
| 流式支持 | 支持 `stream: true` |

### 配置变更

```env
# .env 新增/修改
AR_LLM_PROVIDER=chat2api
AR_CHAT2API_URL=http://127.0.0.1:7860
AR_CHAT2API_MODEL=codex
```

### config.py 新增字段

```python
# 新增到 Settings 类
chat2api_url: str = "http://127.0.0.1:7860"
chat2api_model: str = "codex"
```

### LLM 客户端封装

```python
# src/llm/client.py
"""统一 LLM 客户端，通过 Chat2API 的 OpenAI 兼容接口调用"""

import httpx
from src.config import settings


class LLMClient:
    """OpenAI-compatible LLM client for Chat2API"""

    def __init__(self):
        self.base_url = settings.chat2api_url
        self.model = settings.chat2api_model
        self._client = httpx.Client(timeout=120)

    def chat(self, messages: list[dict], temperature: float | None = 0.7,
             max_tokens: int | None = None) -> str:
        """发送对话请求，返回助手回复文本"""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
            
        resp = self._client.post(
            f"{self.base_url}/v1/chat/completions",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

    def chat_stream(self, messages: list[dict], temperature: float | None = 0.7,
                    max_tokens: int | None = None):
        """流式对话，yield 每个 token"""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
            
        with self._client.stream(
            "POST",
            f"{self.base_url}/v1/chat/completions",
            json=payload,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line or line == "data: [DONE]":
                    continue
                if line.startswith("data: "):
                    import json
                    chunk = json.loads(line[6:])
                    delta = chunk["choices"][0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield content

    def health_check(self) -> bool:
        """检查 Chat2API 是否在线"""
        try:
            resp = self._client.get(f"{self.base_url}/health")
            return resp.status_code == 200
        except httpx.ConnectError:
            return False

    def close(self):
        self._client.close()
```

---

## 三、核心模块设计 — AI 客服对话引擎

### 3.1 Amazon 客服聊天流程分析

Amazon 客服聊天入口路径（需要在浏览器中逐步导航）：

```
1. 进入 "Contact Us" 页面
   URL: https://www.amazon.com/gp/help/customer/contact-us

2. 选择相关订单
   → 页面展示近期订单列表，点击目标订单

3. 选择问题类型
   → "Problem with order" 或类似选项
   → 子类型选择与价格/收费相关的选项

4. 选择联系方式
   → "Chat" （在线聊天）

5. 进入聊天窗口
   → 可能先是 AI bot，然后转接真人
   → 在聊天输入框中发送消息
```

**重要：** Amazon 的客服页面结构和选择器会变化，选择器需要在实际开发中通过 Chrome DevTools MCP 或手动检查确认。以下选择器是**参考值**，需要在实际页面上验证和更新。

### 3.2 对话策略状态机

```
                    ┌───────────────────────┐
                    │       INIT            │
                    │  (准备订单信息)         │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │     NAVIGATING        │
                    │  (导航到客服聊天)       │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │     OPENING           │
                    │  (发送开场白)           │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
              ┌────►│    WAITING_REPLY      │◄──────────┐
              │     │  (等待客服回复)         │           │
              │     └───────────┬───────────┘           │
              │                 │                       │
              │     ┌───────────▼───────────┐           │
              │     │    ANALYZING          │           │
              │     │  (分析客服回复)         │           │
              │     └──┬────┬────┬────┬─────┘           │
              │        │    │    │    │                  │
              │   success refuse safety timeout         │
              │        │    │    │    │                  │
              │        │    │    │    ▼                  │
              │        │    │    │  TIMEOUT              │
              │        │    │    ▼                       │
              │        │    │  SAFETY_STOP               │
              │        │    ▼                            │
              │        │  ┌─────────────────┐           │
              │        │  │  NEGOTIATING    │───reply───┘
              │        │  │  (LLM 生成回复)  │
              │        │  └────────┬────────┘
              │        │           │
              │        │    exceeded max?
              │        │           │ yes
              │        │  ┌────────▼────────┐
              │        │  │  ESCALATING     │───reply───┐
              │        │  │  (请求转接主管)   │          │
              │        │  └────────┬────────┘          │
              │        │           │ refused again      │
              │        │           ▼                    │
              │        │        FAILED                  │
              │        ▼                                │
              │     COMPLETED                          │
              │                                        │
              └────────────────────────────────────────┘
```

### 3.3 文件结构

```
src/
├── llm/
│   ├── __init__.py
│   └── client.py               # LLMClient (Chat2API 调用)
│
├── refund/
│   ├── __init__.py
│   ├── navigator.py            # Amazon 客服页面导航
│   ├── chat_driver.py          # 聊天窗口消息收发
│   ├── strategy.py             # 对话策略状态机
│   ├── prompts.py              # 提示词模板
│   ├── agent.py                # 退款代理（编排层）
│   └── safety.py               # 安全限制和每日配额
│
└── notify/
    ├── __init__.py
    ├── base.py                 # Notifier 抽象基类
    ├── telegram.py             # Telegram Bot 通知
    └── ntfy.py                 # ntfy.sh 通知
```

### 3.4 各文件详细设计

#### 3.4.1 navigator.py — Amazon 客服页面导航

职责：从任意 Amazon 页面导航到指定订单的客服聊天窗口

```python
# src/refund/navigator.py
"""Navigate Amazon's customer service pages to reach the live chat."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from src.browser.stealth import human_scroll, random_delay


class NavResult(Enum):
    SUCCESS = auto()         # 成功打开聊天窗口
    ORDER_NOT_FOUND = auto() # 未找到指定订单
    CHAT_UNAVAILABLE = auto()# 聊天选项不可用
    CAPTCHA = auto()         # 遇到验证码
    ERROR = auto()           # 其他错误


@dataclass
class ChatContext:
    """成功导航后的聊天上下文"""
    page: object                      # Patchright Page
    input_selector: str               # 聊天输入框选择器
    send_selector: str                # 发送按钮选择器
    message_container_selector: str   # 消息容器选择器
    agent_message_selector: str       # 客服消息选择器


class CustomerServiceNavigator:
    """
    导航到 Amazon 客服聊天。

    这是最容易因 Amazon 页面变化而失效的模块。
    所有选择器集中定义在 SELECTORS 字典中，便于维护。
    """

    # ---- 选择器定义（需要在实际页面上验证）----
    # 标记 ⚠️ 的选择器是最可能变化的
    SELECTORS = {
        # Contact Us 页面
        "order_list_item": ".cs-order-card, [data-order-id]",            # ⚠️
        "order_id_text": ".cs-order-id, .order-info",                    # ⚠️
        "problem_category": "[data-item-id*='problem'], .category-item", # ⚠️
        "price_charge_option": "[data-item-id*='charge'], [data-item-id*='price']", # ⚠️
        "chat_button": "#contact-chat-btn, button[data-action='chat']",  # ⚠️

        # 聊天窗口
        "chat_input": "textarea.chat-textarea, #chat-input, textarea[placeholder]", # ⚠️
        "chat_send": "button.send-btn, button[type='submit']",          # ⚠️
        "chat_container": ".chat-messages, #chat-messages",              # ⚠️
        "agent_message": ".agent-bubble, .cs-agent-message",             # ⚠️

        # 安全检测
        "captcha": "#captchacharacters, .a-captcha",
        "identity_verify": "[data-action='verify'], .identity-verification",
    }

    CONTACT_URL = "https://www.amazon.com/gp/help/customer/contact-us"

    def navigate_to_chat(self, page, order_id: str) -> tuple[NavResult, ChatContext | None]:
        """
        完整导航流程：Contact Us → 选择订单 → 选择问题 → 打开聊天

        Returns:
            (NavResult, ChatContext | None)
        """
        # Step 1: 导航到 Contact Us
        page.goto(self.CONTACT_URL)
        random_delay(2, 4)

        # 安全检查
        if self._check_safety(page):
            return NavResult.CAPTCHA, None

        # Step 2: 选择订单
        if not self._select_order(page, order_id):
            return NavResult.ORDER_NOT_FOUND, None

        # Step 3: 选择问题类型
        self._select_problem_category(page)

        # Step 4: 点击聊天按钮
        chat_btn = page.query_selector(self.SELECTORS["chat_button"])
        if not chat_btn:
            return NavResult.CHAT_UNAVAILABLE, None

        chat_btn.click()
        random_delay(3, 6)

        # Step 5: 等待聊天窗口加载
        try:
            page.wait_for_selector(
                self.SELECTORS["chat_input"],
                timeout=15000,
            )
        except Exception:
            return NavResult.CHAT_UNAVAILABLE, None

        ctx = ChatContext(
            page=page,
            input_selector=self.SELECTORS["chat_input"],
            send_selector=self.SELECTORS["chat_send"],
            message_container_selector=self.SELECTORS["chat_container"],
            agent_message_selector=self.SELECTORS["agent_message"],
        )
        return NavResult.SUCCESS, ctx

    def _select_order(self, page, order_id: str) -> bool:
        """在订单列表中点击目标订单"""
        order_cards = page.query_selector_all(self.SELECTORS["order_list_item"])
        for card in order_cards:
            text = card.inner_text()
            if order_id in text:
                card.click()
                random_delay(1, 2)
                return True
        return False

    def _select_problem_category(self, page):
        """选择问题类型（价格/收费相关）"""
        # 先选大类
        cat = page.query_selector(self.SELECTORS["problem_category"])
        if cat:
            cat.click()
            random_delay(1, 2)

        # 再选子类
        sub = page.query_selector(self.SELECTORS["price_charge_option"])
        if sub:
            sub.click()
            random_delay(1, 2)

    def _check_safety(self, page) -> bool:
        """检查是否遇到 CAPTCHA 或身份验证"""
        for key in ("captcha", "identity_verify"):
            if page.query_selector(self.SELECTORS[key]):
                return True
        return False
```

#### 3.4.2 chat_driver.py — 聊天消息收发

职责：在已打开的聊天窗口中收发消息，屏蔽 UI 细节

```python
# src/refund/chat_driver.py
"""Low-level chat message send/receive on the Amazon CS chat widget."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.browser.stealth import human_type, random_delay
from src.refund.navigator import ChatContext


@dataclass
class ChatMessage:
    role: str            # "customer" | "agent"
    content: str
    timestamp: datetime = field(default_factory=datetime.now)


class ChatDriver:
    """操作聊天窗口：发送消息、等待回复、读取历史"""

    def __init__(self, ctx: ChatContext):
        self.ctx = ctx
        self.page = ctx.page
        self._seen_count = 0  # 已读客服消息数

    def send_message(self, text: str) -> None:
        """在聊天输入框中输入消息并发送"""
        input_el = self.page.wait_for_selector(
            self.ctx.input_selector, timeout=10000
        )
        # 清空已有内容
        input_el.click()
        input_el.fill("")
        # 模拟打字
        human_type(input_el, text)
        random_delay(0.3, 0.8)

        # 点发送或按回车
        send_btn = self.page.query_selector(self.ctx.send_selector)
        if send_btn and send_btn.is_visible():
            send_btn.click()
        else:
            input_el.press("Enter")
        random_delay(1, 2)

    def wait_for_agent_reply(self, timeout_sec: int = 90) -> str | None:
        """
        等待新的客服消息出现。

        通过对比消息数量变化来检测新消息。
        超时返回 None。
        """
        deadline = datetime.now().timestamp() + timeout_sec
        initial_count = self._count_agent_messages()

        while datetime.now().timestamp() < deadline:
            random_delay(2, 4)
            current_count = self._count_agent_messages()

            if current_count > initial_count:
                # 新消息出现，再等一会确保消息完整
                random_delay(1, 2)
                messages = self.page.query_selector_all(
                    self.ctx.agent_message_selector
                )
                if messages:
                    latest = messages[-1].inner_text().strip()
                    self._seen_count = current_count
                    return latest
        return None

    def get_all_messages(self) -> list[ChatMessage]:
        """读取聊天窗口中的所有可见消息"""
        # 这里需要根据实际聊天 UI 结构来区分 customer vs agent 消息
        # 以下是通用逻辑
        messages = []
        container = self.page.query_selector(
            self.ctx.message_container_selector
        )
        if not container:
            return messages

        # 所有消息元素（需要根据实际 class 调整）
        all_msgs = container.query_selector_all(
            ".chat-bubble, .message-bubble"
        )
        for msg in all_msgs:
            classes = msg.get_attribute("class") or ""
            role = "agent" if "agent" in classes else "customer"
            content = msg.inner_text().strip()
            if content:
                messages.append(ChatMessage(role=role, content=content))

        return messages

    def is_chat_ended(self) -> bool:
        """检测聊天是否已被客服结束"""
        indicators = [
            "chat has ended",
            "conversation has been closed",
            "thank you for contacting",
        ]
        container = self.page.query_selector(
            self.ctx.message_container_selector
        )
        if not container:
            return False
        text = container.inner_text().lower()
        return any(ind in text for ind in indicators)

    def _count_agent_messages(self) -> int:
        msgs = self.page.query_selector_all(self.ctx.agent_message_selector)
        return len(msgs)
```

#### 3.4.3 strategy.py — 对话策略状态机

```python
# src/refund/strategy.py
"""Refund conversation strategy: state machine + outcome detection."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

from src.config import settings


class RefundState(Enum):
    INIT = auto()
    NAVIGATING = auto()
    OPENING = auto()
    WAITING_REPLY = auto()
    NEGOTIATING = auto()
    ESCALATING = auto()
    COMPLETED = auto()
    FAILED = auto()
    SAFETY_STOP = auto()
    TIMEOUT = auto()


@dataclass
class ConversationLog:
    messages: list[dict] = field(default_factory=list)
    rounds: int = 0              # 我方发送的消息数
    state: RefundState = RefundState.INIT
    refund_amount: float | None = None
    refund_type: str | None = None
    failure_reason: str | None = None

    def add(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})
        if role == "customer":
            self.rounds += 1

    @property
    def is_terminal(self) -> bool:
        return self.state in (
            RefundState.COMPLETED,
            RefundState.FAILED,
            RefundState.SAFETY_STOP,
            RefundState.TIMEOUT,
        )

    @property
    def should_continue(self) -> bool:
        return not self.is_terminal and self.rounds < settings.max_chat_rounds


class OutcomeDetector:
    """分析客服回复，判断对话结果"""

    # 关键词组 — 按优先级从高到低
    SAFETY_KEYWORDS = [
        "verify your identity", "suspicious activity", "unusual activity",
        "account security", "account has been locked", "verify your account",
    ]

    SUCCESS_KEYWORDS = [
        "refund", "credit has been", "adjustment", "applied to your",
        "processed", "issued a", "courtesy credit", "promotional credit",
        "gift card", "we have credited", "amount of $",
    ]

    REJECT_KEYWORDS = [
        "unable to", "cannot", "not eligible", "not possible",
        "unfortunately", "don't have", "policy does not",
        "no longer available", "outside the window",
    ]

    TRANSFER_KEYWORDS = [
        "transfer", "supervisor", "specialist", "another department",
        "escalat",
    ]

    def detect(self, agent_message: str, current_state: RefundState) -> RefundState:
        lower = agent_message.lower()

        # 1. 安全信号 — 最高优先级，立即停止
        if any(kw in lower for kw in self.SAFETY_KEYWORDS):
            return RefundState.SAFETY_STOP

        # 2. 成功信号
        if any(kw in lower for kw in self.SUCCESS_KEYWORDS):
            return RefundState.COMPLETED

        # 3. 转接信号（可能是好事）
        if any(kw in lower for kw in self.TRANSFER_KEYWORDS):
            return RefundState.WAITING_REPLY  # 等待新客服

        # 4. 拒绝信号
        if any(kw in lower for kw in self.REJECT_KEYWORDS):
            if current_state == RefundState.ESCALATING:
                return RefundState.FAILED  # 第二次拒绝
            return RefundState.ESCALATING  # 第一次拒绝 → 升级

        # 5. 默认：继续协商
        return RefundState.NEGOTIATING

    def extract_refund_amount(self, text: str) -> float | None:
        """从客服回复中提取退款金额"""
        import re
        patterns = [
            r'\$(\d+\.?\d*)\s*(?:refund|credit|adjustment)',
            r'(?:refund|credit|adjustment)\s*(?:of\s*)?\$(\d+\.?\d*)',
            r'(?:issued|applied|credited)\s*\$(\d+\.?\d*)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return float(match.group(1))
        return None

    def extract_refund_type(self, text: str) -> str | None:
        """判断退款形式"""
        lower = text.lower()
        if "gift card" in lower or "gift-card" in lower:
            return "gift_card"
        if "promotional" in lower or "promo" in lower:
            return "promotional_credit"
        if "credit card" in lower or "original payment" in lower:
            return "credit_card"
        if "refund" in lower:
            return "refund"
        return None
```

#### 3.4.4 prompts.py — 提示词模板

```python
# src/refund/prompts.py
"""LLM prompt templates for the refund chat agent."""

SYSTEM_PROMPT = """\
You are a helpful assistant guiding a customer through an Amazon customer service chat \
to request a price adjustment (partial refund) on a recent order.

## Your role
Generate the customer's next chat message. Be polite, natural, and concise — \
like a normal person texting customer support, not a formal letter.

## Context
- Order ID: {order_id}
- Item: {item_title}
- Purchase date: {purchase_date}
- Purchase price: ${purchase_price:.2f}
- Current price: ${current_price:.2f}
- Price difference: ${price_diff:.2f}

## Rules
1. Sound like a regular customer. Use casual but polite language.
2. Never mention automation, scripts, bots, or AI.
3. Keep messages short — 1-3 sentences max.
4. Stick to facts. Do not fabricate order details.
5. If the agent offers a gift card or promotional credit instead of a direct refund, \
accept it graciously.
6. If refused, politely ask if a supervisor could review the request.
7. If refused again, thank them and end the conversation.
8. Do NOT ask questions that the agent already answered.
"""

OPENING_TEMPLATE = """\
Hi! I recently bought {item_title} (order #{order_id}) for ${purchase_price:.2f}, \
and I noticed the price has dropped to ${current_price:.2f}. \
That's a ${price_diff:.2f} difference. \
Is there any way to get a price adjustment or partial refund?\
"""

ESCALATION_TEMPLATE = """\
I understand. Would it be possible to have a supervisor or specialist take a look? \
I've been a loyal customer and would really appreciate any help with this.\
"""

ACCEPT_CREDIT_TEMPLATE = """\
That works for me, thank you! I appreciate the help.\
"""

CLOSING_TEMPLATE = """\
I understand. Thank you for your time and help. Have a great day!\
"""


def build_system_prompt(order_id: str, item_title: str, purchase_date: str,
                        purchase_price: float, current_price: float,
                        price_diff: float) -> str:
    return SYSTEM_PROMPT.format(
        order_id=order_id,
        item_title=item_title,
        purchase_date=purchase_date,
        purchase_price=purchase_price,
        current_price=current_price,
        price_diff=price_diff,
    )


def build_opening_message(order_id: str, item_title: str,
                          purchase_price: float, current_price: float,
                          price_diff: float) -> str:
    return OPENING_TEMPLATE.format(
        order_id=order_id,
        item_title=item_title,
        purchase_price=purchase_price,
        current_price=current_price,
        price_diff=price_diff,
    )
```

#### 3.4.5 safety.py — 安全限制

```python
# src/refund/safety.py
"""Safety limits: daily quota, cooldown, consecutive failure tracking."""

from __future__ import annotations

from datetime import datetime, timedelta

from src.config import settings
from src.db.connection import db


class SafetyGuard:
    """执行安全限制，保护 Amazon 账户"""

    # 硬编码上限，不可通过配置覆盖
    ABSOLUTE_MAX_DAILY = 10
    CONSECUTIVE_FAIL_LIMIT = 3
    COOLDOWN_HOURS = 24

    def can_proceed(self) -> tuple[bool, str]:
        """检查是否可以执行下一个退款请求"""
        with db.connection() as conn:
            # 1. 检查每日配额
            daily_count = self._get_today_count(conn)
            limit = min(settings.max_daily_refunds, self.ABSOLUTE_MAX_DAILY)
            if daily_count >= limit:
                return False, f"Daily limit reached ({daily_count}/{limit})"

            # 2. 检查连续失败冷却
            consec_fails = self._get_consecutive_failures(conn)
            if consec_fails >= self.CONSECUTIVE_FAIL_LIMIT:
                last_fail_time = self._get_last_failure_time(conn)
                if last_fail_time:
                    cooldown_until = last_fail_time + timedelta(
                        hours=self.COOLDOWN_HOURS
                    )
                    if datetime.now() < cooldown_until:
                        remaining = cooldown_until - datetime.now()
                        return False, (
                            f"{consec_fails} consecutive failures. "
                            f"Cooldown: {remaining.seconds // 3600}h remaining"
                        )

        return True, "OK"

    def _get_today_count(self, conn) -> int:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM refund_requests
                WHERE attempted_at >= TRUNC(SYSDATE)
                  AND status IN ('success', 'failed', 'in_progress')
            """)
            return int(cur.fetchone()[0])

    def _get_consecutive_failures(self, conn) -> int:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM (
                    SELECT status,
                           ROW_NUMBER() OVER (ORDER BY attempted_at DESC) AS rn
                    FROM refund_requests
                    WHERE status IN ('success', 'failed')
                )
                WHERE status = 'failed'
                  AND rn <= :limit
            """, {"limit": self.CONSECUTIVE_FAIL_LIMIT})
            return int(cur.fetchone()[0])

    def _get_last_failure_time(self, conn) -> datetime | None:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT MAX(attempted_at) FROM refund_requests
                WHERE status = 'failed'
            """)
            row = cur.fetchone()
            return row[0] if row and row[0] else None
```

#### 3.4.6 agent.py — 退款代理（编排层）

```python
# src/refund/agent.py
"""Top-level refund agent: orchestrates navigator, chat driver, LLM, and strategy."""

from __future__ import annotations

import json
from datetime import datetime

from rich.console import Console

from src.browser.connection import BrowserManager
from src.browser.stealth import random_delay
from src.config import settings
from src.db.connection import db
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
    """
    编排完整退款流程的顶层代理。

    流程:
    1. 安全检查（配额、冷却）
    2. 导航到客服聊天
    3. 发送开场白
    4. 循环：等待回复 → 分析 → LLM 生成回复 → 发送
    5. 记录结果到数据库
    """

    def __init__(self, browser: BrowserManager):
        self.browser = browser
        self.navigator = CustomerServiceNavigator()
        self.detector = OutcomeDetector()
        self.safety = SafetyGuard()
        self.llm = LLMClient()

    def process_request(self, request: RefundRequest,
                        order_id: str, item_title: str,
                        purchase_date: str) -> ConversationLog:
        """
        处理单个退款请求。

        Args:
            request: 退款请求记录
            order_id: Amazon 订单号
            item_title: 商品名称
            purchase_date: 购买日期字符串

        Returns:
            ConversationLog 包含完整对话记录和最终状态
        """
        log = ConversationLog()

        # 1. 安全检查
        can_go, reason = self.safety.can_proceed()
        if not can_go:
            console.print(f"[red]Safety block: {reason}[/red]")
            log.state = RefundState.FAILED
            log.failure_reason = f"Safety: {reason}"
            return log

        # 2. 打开新页面并导航
        page = self.browser.new_page()
        log.state = RefundState.NAVIGATING

        try:
            console.print(f"Navigating to CS chat for order {order_id}...")
            nav_result, chat_ctx = self.navigator.navigate_to_chat(page, order_id)

            if nav_result != NavResult.SUCCESS:
                console.print(f"[red]Navigation failed: {nav_result.name}[/red]")
                log.state = RefundState.FAILED
                log.failure_reason = f"Navigation: {nav_result.name}"
                return log

            # 3. 初始化聊天驱动
            driver = ChatDriver(chat_ctx)

            # 4. 发送开场白
            opening = build_opening_message(
                order_id, item_title,
                request.purchase_price, request.current_price, request.price_diff,
            )
            driver.send_message(opening)
            log.add("customer", opening)
            log.state = RefundState.OPENING
            console.print(f"[blue]>>> {opening}[/blue]")

            # 5. 对话循环
            system_prompt = build_system_prompt(
                order_id, item_title, purchase_date,
                request.purchase_price, request.current_price, request.price_diff,
            )

            while log.should_continue:
                # 等待客服回复
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

                # 分析回复
                new_state = self.detector.detect(agent_reply, log.state)
                log.state = new_state

                # 提取退款信息
                if new_state == RefundState.COMPLETED:
                    log.refund_amount = self.detector.extract_refund_amount(agent_reply)
                    log.refund_type = self.detector.extract_refund_type(agent_reply)
                    # 发送感谢
                    driver.send_message(ACCEPT_CREDIT_TEMPLATE)
                    log.add("customer", ACCEPT_CREDIT_TEMPLATE)
                    console.print(f"[bold green]Refund obtained: ${log.refund_amount}[/bold green]")
                    break

                if new_state == RefundState.SAFETY_STOP:
                    console.print("[bold red]Safety signal detected! Stopping.[/bold red]")
                    log.failure_reason = "Safety signal in agent reply"
                    break

                if new_state == RefundState.FAILED:
                    driver.send_message(CLOSING_TEMPLATE)
                    log.add("customer", CLOSING_TEMPLATE)
                    log.failure_reason = "Refund rejected after escalation"
                    break

                # 生成回复
                if new_state == RefundState.ESCALATING:
                    reply = ESCALATION_TEMPLATE
                else:
                    reply = self._llm_reply(system_prompt, log)

                driver.send_message(reply)
                log.add("customer", reply)
                console.print(f"[blue]>>> {reply}[/blue]")
                random_delay(1, 2)

            # 检查是否因轮数超限退出
            if not log.is_terminal:
                log.state = RefundState.TIMEOUT
                log.failure_reason = f"Max rounds exceeded ({log.rounds})"

        finally:
            page.close()
            self.llm.close()

        return log

    def _llm_reply(self, system_prompt: str, log: ConversationLog) -> str:
        """用 LLM 生成下一条客户消息"""
        messages = [{"role": "system", "content": system_prompt}]

        # 将对话历史转换为 LLM 格式
        for msg in log.messages:
            role = "assistant" if msg["role"] == "agent" else "user"
            messages.append({"role": role, "content": msg["content"]})

        messages.append({
            "role": "user",
            "content": (
                "Generate the customer's next message. "
                "Keep it short (1-3 sentences), natural, and focused on getting the refund."
            ),
        })

        return self.llm.chat(messages, temperature=0.7, max_tokens=200)
```

---

## 四、数据库变更

### 4.1 RefundRepository 新增方法

```python
# 新增到 src/db/repository.py 的 RefundRepository 类

def list_pending(self, connection, limit: int | None = None) -> list[RefundRequest]:
    """获取待处理的退款请求，按差价金额降序"""
    sql = """
        SELECT r.refund_id, r.item_id, r.purchase_price, r.current_price,
               r.price_diff, r.status, r.refund_amount, r.refund_type,
               r.conversation_log, r.failure_reason, r.attempted_at
        FROM refund_requests r
        WHERE r.status = 'pending'
        ORDER BY r.price_diff DESC
    """
    binds = {}
    if limit:
        sql = f"SELECT * FROM ({sql}) WHERE ROWNUM <= :limit"
        binds["limit"] = limit
    with connection.cursor() as cur:
        cur.execute(sql, binds)
        rows = cur.fetchall()
    return [self._row_to_request(row) for row in rows]


def update_result(self, connection, refund_id: int,
                  status: str, refund_amount: float | None = None,
                  refund_type: str | None = None,
                  conversation_log: str | None = None,
                  failure_reason: str | None = None) -> None:
    """更新退款请求结果"""
    with connection.cursor() as cur:
        cur.execute("""
            UPDATE refund_requests
            SET status = :status,
                refund_amount = :refund_amount,
                refund_type = :refund_type,
                conversation_log = :conversation_log,
                failure_reason = :failure_reason,
                attempted_at = CURRENT_TIMESTAMP
            WHERE refund_id = :refund_id
        """, {
            "status": status,
            "refund_amount": refund_amount,
            "refund_type": refund_type,
            "conversation_log": conversation_log,
            "failure_reason": failure_reason,
            "refund_id": refund_id,
        })


def get_item_details(self, connection, item_id: int) -> dict | None:
    """获取退款请求关联的商品和订单信息"""
    with connection.cursor() as cur:
        cur.execute("""
            SELECT i.order_id, i.asin, i.title, i.purchase_price,
                   i.product_url, i.seller, o.order_date
            FROM items i
            JOIN orders o ON o.order_id = i.order_id
            WHERE i.item_id = :item_id
        """, {"item_id": item_id})
        row = cur.fetchone()
    if not row:
        return None
    return {
        "order_id": row[0],
        "asin": row[1],
        "title": row[2],
        "purchase_price": float(row[3]),
        "product_url": row[4],
        "seller": row[5],
        "purchase_date": row[6].strftime("%Y-%m-%d") if row[6] else "",
    }


@staticmethod
def _row_to_request(row) -> RefundRequest:
    return RefundRequest(
        item_id=row[1],
        purchase_price=float(row[2]),
        current_price=float(row[3]),
        price_diff=float(row[4]),
        status=row[5],
        refund_amount=float(row[6]) if row[6] else None,
        refund_type=row[7],
        conversation_log=row[8],
        failure_reason=row[9],
        attempted_at=row[10],
    )
```

### 4.2 RefundRequest 模型增加 refund_id

```python
# 修改 src/db/models.py 的 RefundRequest
@dataclass(slots=True)
class RefundRequest:
    item_id: int
    purchase_price: float
    current_price: float
    price_diff: float
    status: str = "pending"
    refund_amount: float | None = None
    refund_type: str | None = None
    conversation_log: str | None = None
    failure_reason: str | None = None
    attempted_at: datetime | None = None
    refund_id: int | None = None          # ← 新增
```

---

## 五、CLI 新增命令

```python
# 新增到 src/cli.py

@app.command()
def refund(
    order_id: str | None = typer.Argument(None, help="Process a specific order. Omit to process the queue."),
    dry_run: bool = typer.Option(False, help="Navigate and show plan but don't chat."),
    limit: int = typer.Option(5, help="Max requests to process from queue."),
) -> None:
    """Execute AI-powered refund conversations with Amazon CS."""
    from src.llm.client import LLMClient
    from src.refund.agent import RefundAgent

    # 1. 检查 LLM 可用性
    llm = LLMClient()
    if not llm.health_check():
        console.print("[red]Chat2API is not reachable. Start it first.[/red]")
        raise typer.Exit(1)
    llm.close()

    db.init_pool()
    browser = BrowserManager()
    browser.connect()

    try:
        agent = RefundAgent(browser)
        refund_repo = RefundRepository()

        with db.connection() as conn:
            if order_id:
                # 处理指定订单
                # ... 查找对应 refund_request ...
                pass
            else:
                # 处理队列
                pending = refund_repo.list_pending(conn, limit=limit)

            if not pending:
                console.print("[yellow]No pending refund requests.[/yellow]")
                return

            console.print(f"Found {len(pending)} pending requests.")

            for req in pending:
                details = refund_repo.get_item_details(conn, req.item_id)
                if not details:
                    continue

                console.print(f"\n{'='*60}")
                console.print(f"Order: {details['order_id']} | {details['title'][:50]}")
                console.print(f"Price drop: ${req.purchase_price:.2f} → ${req.current_price:.2f} (−${req.price_diff:.2f})")

                if dry_run:
                    console.print("[yellow]Dry run — skipping chat[/yellow]")
                    continue

                # 执行退款对话
                log = agent.process_request(
                    req,
                    order_id=details["order_id"],
                    item_title=details["title"],
                    purchase_date=details["purchase_date"],
                )

                # 保存结果
                import json
                refund_repo.update_result(
                    conn,
                    refund_id=req.refund_id,
                    status=log.state.name.lower(),
                    refund_amount=log.refund_amount,
                    refund_type=log.refund_type,
                    conversation_log=json.dumps(log.messages, ensure_ascii=False),
                    failure_reason=log.failure_reason,
                )
                conn.commit()

                console.print(f"Result: {log.state.name} | Refund: ${log.refund_amount or 0:.2f}")

    finally:
        browser.close()
        db.close()


@app.command()
def test_llm(
    message: str = typer.Option("Hello, can you help me?", help="Test message to send."),
) -> None:
    """Test Chat2API connectivity and response."""
    from src.llm.client import LLMClient

    llm = LLMClient()
    if not llm.health_check():
        console.print("[red]Chat2API is offline.[/red]")
        raise typer.Exit(1)

    console.print(f"[green]Chat2API online — model: {llm.model}[/green]")
    console.print(f"Sending: {message}")

    reply = llm.chat([{"role": "user", "content": message}])
    console.print(f"[cyan]Reply: {reply}[/cyan]")
    llm.close()
```

---

## 六、测试方案（Phase 2）

### 6.1 新增测试文件

```
tests/
├── test_llm_client.py        # LLM 客户端测试
├── test_strategy.py           # 对话策略状态机测试
├── test_prompts.py            # 提示词生成测试
├── test_safety.py             # 安全限制测试
├── test_outcome_detector.py   # 结果检测测试
└── e2e/
    └── test_refund_flow.py    # 端到端退款测试（手动）
```

### 6.2 L1 — 单元测试

```python
# tests/test_strategy.py
"""对话策略状态机测试 — 无外部依赖"""

from src.refund.strategy import ConversationLog, OutcomeDetector, RefundState


class TestOutcomeDetector:
    def setup_method(self):
        self.detector = OutcomeDetector()

    # ---- 成功检测 ----
    def test_detects_refund_issued(self):
        state = self.detector.detect(
            "I've issued a $5.00 refund to your credit card.",
            RefundState.NEGOTIATING,
        )
        assert state == RefundState.COMPLETED

    def test_detects_promotional_credit(self):
        state = self.detector.detect(
            "I've applied a $3.50 promotional credit to your account.",
            RefundState.NEGOTIATING,
        )
        assert state == RefundState.COMPLETED

    def test_detects_gift_card(self):
        state = self.detector.detect(
            "I can offer you a courtesy credit of $4.00 as a gift card balance.",
            RefundState.NEGOTIATING,
        )
        assert state == RefundState.COMPLETED

    # ---- 拒绝 → 升级 ----
    def test_first_rejection_escalates(self):
        state = self.detector.detect(
            "Unfortunately, we are unable to process a price adjustment.",
            RefundState.NEGOTIATING,
        )
        assert state == RefundState.ESCALATING

    def test_second_rejection_fails(self):
        state = self.detector.detect(
            "I'm sorry, it is not possible to adjust the price.",
            RefundState.ESCALATING,
        )
        assert state == RefundState.FAILED

    # ---- 安全信号 ----
    def test_safety_identity_verify(self):
        state = self.detector.detect(
            "For security, please verify your identity before we proceed.",
            RefundState.NEGOTIATING,
        )
        assert state == RefundState.SAFETY_STOP

    def test_safety_suspicious(self):
        state = self.detector.detect(
            "We detected suspicious activity on your account.",
            RefundState.OPENING,
        )
        assert state == RefundState.SAFETY_STOP

    # ---- 转接 ----
    def test_transfer_keeps_waiting(self):
        state = self.detector.detect(
            "Let me transfer you to a specialist who can help.",
            RefundState.NEGOTIATING,
        )
        assert state == RefundState.WAITING_REPLY

    # ---- 默认 ----
    def test_neutral_message_negotiates(self):
        state = self.detector.detect(
            "Sure, let me look into that for you. One moment please.",
            RefundState.OPENING,
        )
        assert state == RefundState.NEGOTIATING


class TestRefundAmountExtraction:
    def setup_method(self):
        self.detector = OutcomeDetector()

    def test_extract_dollar_amount(self):
        amount = self.detector.extract_refund_amount(
            "I've issued a $5.00 refund to your original payment method."
        )
        assert amount == 5.00

    def test_extract_credit_amount(self):
        amount = self.detector.extract_refund_amount(
            "A promotional credit of $12.99 has been applied."
        )
        assert amount == 12.99

    def test_no_amount(self):
        amount = self.detector.extract_refund_amount(
            "Let me check that for you."
        )
        assert amount is None


class TestRefundTypeExtraction:
    def setup_method(self):
        self.detector = OutcomeDetector()

    def test_gift_card(self):
        assert self.detector.extract_refund_type("gift card balance") == "gift_card"

    def test_promotional(self):
        assert self.detector.extract_refund_type("promotional credit") == "promotional_credit"

    def test_credit_card(self):
        assert self.detector.extract_refund_type("original payment method") is None  # no "credit card" keyword
        assert self.detector.extract_refund_type("credit card refund") == "credit_card"


class TestConversationLog:
    def test_round_counting(self):
        log = ConversationLog()
        log.add("customer", "Hi")
        log.add("agent", "Hello")
        log.add("customer", "I need help")
        assert log.rounds == 2

    def test_terminal_states(self):
        log = ConversationLog()
        log.state = RefundState.COMPLETED
        assert log.is_terminal
        assert not log.should_continue

    def test_max_rounds_stops(self):
        log = ConversationLog()
        for i in range(10):
            log.add("customer", f"msg {i}")
        assert not log.should_continue
```

```python
# tests/test_prompts.py
"""提示词生成测试"""

from src.refund.prompts import build_opening_message, build_system_prompt


def test_opening_message_contains_order():
    msg = build_opening_message(
        order_id="111-2222222-3333333",
        item_title="USB-C Cable",
        purchase_price=19.99,
        current_price=14.99,
        price_diff=5.00,
    )
    assert "111-2222222-3333333" in msg
    assert "USB-C Cable" in msg
    assert "19.99" in msg
    assert "14.99" in msg
    assert "5.00" in msg


def test_system_prompt_has_rules():
    prompt = build_system_prompt(
        order_id="111-2222222-3333333",
        item_title="USB-C Cable",
        purchase_date="2026-02-15",
        purchase_price=19.99,
        current_price=14.99,
        price_diff=5.00,
    )
    assert "automation" in prompt.lower()  # rule about not mentioning automation
    assert "1-3 sentences" in prompt
    assert "19.99" in prompt
```

```python
# tests/test_llm_client.py
"""LLM 客户端测试 — 需要 Chat2API 运行"""

import pytest
from src.llm.client import LLMClient


@pytest.fixture
def llm():
    client = LLMClient()
    yield client
    client.close()


@pytest.mark.skipif(
    not LLMClient().health_check(),
    reason="Chat2API not running",
)
class TestLLMClient:
    def test_health_check(self, llm):
        assert llm.health_check()

    def test_simple_chat(self, llm):
        reply = llm.chat([{"role": "user", "content": "Say 'hello' and nothing else."}])
        assert len(reply) > 0
        assert "hello" in reply.lower()

    def test_chat_with_system_prompt(self, llm):
        reply = llm.chat([
            {"role": "system", "content": "You are a helpful assistant. Always respond in exactly one word."},
            {"role": "user", "content": "What color is the sky?"},
        ], max_tokens=10)
        assert len(reply.split()) <= 5  # roughly one word
```

```python
# tests/test_safety.py
"""安全限制测试 — 需要 Oracle DB"""

import pytest


@pytest.mark.skipif(
    True,  # 替换为 DB 可用性检查
    reason="Oracle DB not available",
)
class TestSafetyGuard:
    def test_allows_first_request(self):
        from src.refund.safety import SafetyGuard
        guard = SafetyGuard()
        can_go, reason = guard.can_proceed()
        # 如果数据库中没有今天的请求，应该允许
        assert can_go or "limit" in reason.lower()
```

### 6.3 L2 — LLM 集成测试（需要 Chat2API）

```python
# tests/test_llm_integration.py
"""测试 LLM 在退款场景中的表现"""

import pytest
from src.llm.client import LLMClient
from src.refund.prompts import build_system_prompt


@pytest.mark.skipif(
    not LLMClient().health_check(),
    reason="Chat2API not running",
)
class TestLLMRefundScenarios:
    """验证 LLM 在退款对话中生成合理回复"""

    @pytest.fixture
    def llm(self):
        client = LLMClient()
        yield client
        client.close()

    @pytest.fixture
    def system_prompt(self):
        return build_system_prompt(
            order_id="111-2222222-3333333",
            item_title="Anker USB-C Cable 6ft",
            purchase_date="2026-02-20",
            purchase_price=15.99,
            current_price=11.99,
            price_diff=4.00,
        )

    def test_generates_natural_reply(self, llm, system_prompt):
        """LLM 应生成自然的客户回复，不提及 AI"""
        reply = llm.chat([
            {"role": "system", "content": system_prompt},
            {"role": "assistant", "content": "Sure, let me look into order #111-2222222-3333333 for you."},
            {"role": "user", "content": "Generate the customer's next message."},
        ])
        assert len(reply) > 10
        assert "bot" not in reply.lower()
        assert "script" not in reply.lower()
        assert "automat" not in reply.lower()

    def test_reply_mentions_price(self, llm, system_prompt):
        """LLM 回复应提及价格差异"""
        reply = llm.chat([
            {"role": "system", "content": system_prompt},
            {"role": "assistant", "content": "I see your order. How can I help?"},
            {"role": "user", "content": "Generate the customer's next message."},
        ])
        # 应提及价格相关内容
        price_related = any(kw in reply.lower() for kw in
                          ["price", "$", "drop", "lower", "difference", "adjust"])
        assert price_related

    def test_reply_is_concise(self, llm, system_prompt):
        """回复应简洁（不超过 5 句）"""
        reply = llm.chat([
            {"role": "system", "content": system_prompt},
            {"role": "assistant", "content": "Let me check on that for you."},
            {"role": "user", "content": "Generate the customer's next message."},
        ], max_tokens=200)
        sentences = [s.strip() for s in reply.replace("!", ".").replace("?", ".").split(".") if s.strip()]
        assert len(sentences) <= 5
```

### 6.4 L4 — 端到端退款测试（手动监督）

```python
# tests/e2e/test_refund_flow.py
"""
端到端退款测试 — 需要:
1. Chrome 已启动 --remote-debugging-port=9222
2. 用户已登录 Amazon
3. Oracle DB 已配置
4. Chat2API 已运行
5. 数据库中已有 pending 退款请求

运行: pytest tests/e2e/test_refund_flow.py -v -s -m manual
"""

import pytest


@pytest.mark.manual
class TestRefundE2E:

    def test_llm_health(self):
        """前置检查：LLM 服务是否在线"""
        from src.llm.client import LLMClient
        llm = LLMClient()
        assert llm.health_check(), "Chat2API is offline"
        llm.close()

    def test_navigate_to_contact_us(self):
        """测试能否导航到 Contact Us 页面"""
        from src.browser.connection import BrowserManager
        from src.refund.navigator import CustomerServiceNavigator

        mgr = BrowserManager()
        mgr.connect()
        page = mgr.new_page()
        nav = CustomerServiceNavigator()

        page.goto(nav.CONTACT_URL)
        import time; time.sleep(3)

        # 检查页面是否加载（应该看到某些 CS 相关元素）
        title = page.title()
        print(f"Page title: {title}")
        assert "amazon" in title.lower()

        page.close()
        mgr.close()

    def test_dry_run_refund(self):
        """Dry-run 模式测试完整流程（不实际聊天）"""
        import subprocess
        result = subprocess.run(
            ["python", "-m", "src.cli", "refund", "--dry-run", "--limit", "1"],
            capture_output=True, text=True,
            cwd="/home/ubuntu/scripts/amazon-refund",
        )
        print(result.stdout)
        print(result.stderr)
        # dry run 不应该出错
        assert result.returncode == 0 or "No pending" in result.stdout
```

### 6.5 测试运行命令总结

```bash
# Phase 2 单元测试（无外部依赖）
pytest tests/test_strategy.py tests/test_prompts.py -v

# LLM 集成测试（需要 Chat2API）
pytest tests/test_llm_client.py tests/test_llm_integration.py -v

# 安全限制测试（需要 Oracle DB）
pytest tests/test_safety.py -v

# 端到端测试（需要一切就绪 + 手动监督）
pytest tests/e2e/test_refund_flow.py -v -s -m manual

# 全部 Phase 2 测试
pytest tests/ -v --ignore=tests/e2e/ -k "strategy or prompts or llm or safety or outcome"
```

---

## 七、实现顺序

按依赖关系排序，逐步构建：

```
Step 1: config.py 新增 chat2api 配置
        ↓
Step 2: src/llm/client.py — LLM 客户端
        → 验证: ar test-llm
        ↓
Step 3: src/refund/prompts.py — 提示词模板
        → 验证: tests/test_prompts.py
        ↓
Step 4: src/refund/strategy.py — 状态机 + 结果检测
        → 验证: tests/test_strategy.py
        ↓
Step 5: src/refund/safety.py — 安全限制
        → 验证: tests/test_safety.py
        ↓
Step 6: src/db/repository.py — RefundRepository 新增方法
        ↓
Step 7: src/refund/navigator.py — CS 页面导航
        → 验证: 手动测试导航（ar refund --dry-run）
        → ⚠️ 这一步需要通过 Chrome DevTools MCP 或手动检查确认选择器
        ↓
Step 8: src/refund/chat_driver.py — 聊天消息收发
        → ⚠️ 同上，选择器需要实际页面验证
        ↓
Step 9: src/refund/agent.py — 退款代理编排
        ↓
Step 10: src/cli.py — 新增 refund 和 test-llm 命令
         → 验证: ar refund --dry-run
         → 验证: ar refund --limit 1 （首次真实退款）
```

### 关键风险点

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Amazon CS 页面选择器失效 | navigator/chat_driver 无法工作 | 选择器集中管理 + Chrome DevTools MCP 辅助调试 |
| 客服 AI bot 无法处理退款 | 需要转接真人 | strategy 支持 TRANSFER 状态，等待新客服 |
| LLM 生成不当内容 | 暴露自动化身份 | 严格 system prompt + 回复长度限制 |
| 账户安全检测 | 触发验证/封号 | SafetyGuard 多层保护 + 立即停止 |
| Oracle DB CLOB 写入 | conversation_log 存储问题 | 使用 oracledb CLOB 类型绑定 |

---

## 八、.env 配置更新

```env
# .env 完整配置（Phase 2 新增项标记 ★）

# Chrome / CDP
AR_CDP_PORT=9222

# Oracle DB
AR_DB_USER=ADMIN
AR_DB_PASSWORD=Oracle4free!
AR_DB_DSN=(description= (retry_count=20)(retry_delay=3)(address=(protocol=tcps)(port=1522)(host=adb.us-ashburn-1.oraclecloud.com))(connect_data=(service_name=gf98deba733cd12_amazon_high.adb.oraclecloud.com))(security=(ssl_server_dn_match=yes)))
AR_DB_WALLET_DIR=/home/ubuntu/.oracle
AR_DB_WALLET_PASSWORD=Oracle4free!

# ★ LLM — Chat2API
AR_LLM_PROVIDER=chat2api
AR_CHAT2API_URL=http://127.0.0.1:7860
AR_CHAT2API_MODEL=codex

# Refund rules
AR_MIN_REFUND_AMOUNT=2.0
AR_MIN_REFUND_PCT=5.0
AR_AMAZON_ONLY=true
AR_MAX_DAILY_REFUNDS=5
AR_MAX_CHAT_ROUNDS=10

# Price check scheduling
AR_CHECK_INTERVAL_HOURS=6.0
AR_INTERVAL_JITTER_PCT=0.3

# ★ Notifications (Phase 2)
AR_TELEGRAM_BOT_TOKEN=
AR_TELEGRAM_CHAT_ID=
AR_NTFY_TOPIC=
AR_NTFY_SERVER=https://ntfy.sh
```
