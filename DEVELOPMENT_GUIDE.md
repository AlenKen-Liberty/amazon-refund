# Amazon 价格追踪与自动退款工具 — 编程指导文档

> 基于设计书 v1.0，结合实际技术调整
> 日期：2026-03-18

---

## 一、技术路线调整说明

| 原设计 | 调整后 | 原因 |
|--------|--------|------|
| Playwright 自动登录 | CDP 连接用户已登录的浏览器 | 用户自行登录，避免凭据管理和 2FA 复杂度 |
| Playwright | **Patchright** (v1.58.2) | Playwright 的反检测分支，过 Cloudflare/Akamai 等 |
| PostgreSQL | **Oracle DB (OCI)** + python-oracledb | 用户提供 OCI 数据库 |
| React 仪表盘 | 暂不实现，CLI 优先 | 当前阶段不需要 |
| Docker 部署 | 暂不实现 | 当前阶段不需要 |

---

## 二、技术栈确认

| 层级 | 技术 | 版本 | 说明 |
|------|------|------|------|
| 浏览器自动化 | Patchright (Python) | 1.58.2 | Playwright 的反检测 fork，API 完全兼容，仅支持 Chromium |
| 浏览器连接 | CDP (Chrome DevTools Protocol) | — | 连接用户已打开并登录的 Chrome |
| AI 辅助 (可选) | Chrome DevTools MCP | latest | Google 官方 MCP server，可让 Claude Code 直接操控浏览器 |
| LLM 引擎 | Ollama (本地) / Claude API / OpenAI API | — | 客服对话生成 |
| 数据库 | Oracle DB (OCI) + python-oracledb | 3.x | Thin 模式，无需安装 Oracle Client |
| 任务调度 | APScheduler | 3.x | 定时价格检查 |
| 通知 | Telegram Bot / ntfy.sh | — | 降价和退款结果通知 |
| CLI 框架 | Typer / Click | — | 命令行交互 |
| 配置管理 | Pydantic Settings + .env | — | 类型安全的配置 |

---

## 三、项目结构

```
amazon-refund/
├── pyproject.toml              # 项目配置 & 依赖
├── .env.example                # 环境变量模板
├── .env                        # 实际配置（git忽略）
├── .gitignore
├── README.md
│
├── src/
│   ├── __init__.py
│   ├── cli.py                  # CLI 入口 (Typer)
│   ├── config.py               # 配置管理 (Pydantic Settings)
│   │
│   ├── browser/                # 浏览器控制层
│   │   ├── __init__.py
│   │   ├── connection.py       # CDP 连接管理
│   │   └── stealth.py          # 反检测辅助（打字延迟、随机滚动等）
│   │
│   ├── collector/              # Module 1: 订单采集
│   │   ├── __init__.py
│   │   ├── order_scraper.py    # 订单页面解析
│   │   └── parsers.py          # HTML 解析器（订单号、ASIN、价格等）
│   │
│   ├── monitor/                # Module 2: 价格监控
│   │   ├── __init__.py
│   │   ├── price_checker.py    # 价格检查主逻辑
│   │   ├── extractors/         # 4种价格提取策略
│   │   │   ├── __init__.py
│   │   │   ├── jsonld.py       # JSON-LD schema.org
│   │   │   ├── css_selector.py # Amazon CSS 选择器
│   │   │   ├── regex.py        # 正则匹配
│   │   │   └── llm.py          # LLM fallback
│   │   └── voter.py            # 投票决策器
│   │
│   ├── analyzer/               # Module 3: 降价分析
│   │   ├── __init__.py
│   │   └── price_drop.py       # 降价检测与退款队列生成
│   │
│   ├── refund/                 # Module 4: AI 客服对话
│   │   ├── __init__.py
│   │   ├── chat_agent.py       # 客服聊天自动化
│   │   ├── prompts.py          # LLM 提示词模板
│   │   └── strategy.py         # 对话策略状态机
│   │
│   ├── notify/                 # Module 5: 通知
│   │   ├── __init__.py
│   │   ├── telegram.py
│   │   └── ntfy.py
│   │
│   ├── db/                     # 数据库层
│   │   ├── __init__.py
│   │   ├── connection.py       # Oracle DB 连接管理
│   │   ├── models.py           # 数据模型定义
│   │   └── migrations.py       # 表结构初始化
│   │
│   └── utils/                  # 工具函数
│       ├── __init__.py
│       ├── retry.py            # 重试装饰器
│       └── humanize.py         # 人类行为模拟
│
├── tests/                      # 测试
│   ├── conftest.py
│   ├── test_parsers.py
│   ├── test_extractors.py
│   ├── test_voter.py
│   ├── test_price_drop.py
│   ├── test_db.py
│   └── fixtures/               # 测试用 HTML 样本
│       ├── order_page.html
│       ├── product_page.html
│       └── chat_page.html
│
├── scripts/                    # 辅助脚本
│   ├── init_db.py              # 数据库初始化
│   └── launch_chrome.sh        # 启动带 CDP 的 Chrome
│
└── prompts/                    # LLM 提示词文件
    ├── refund_system.txt        # 系统提示词
    └── refund_user.txt          # 用户提示词模板
```

---

## 四、核心技术实现指南

### 4.1 浏览器连接 — CDP + Patchright

**用户手动启动 Chrome（带远程调试端口）：**

```bash
#!/bin/bash
# scripts/launch_chrome.sh
# 启动带 CDP 的 Chrome，用户自行登录 Amazon

google-chrome \
  --remote-debugging-port=9222 \
  --remote-debugging-address=127.0.0.1 \
  --user-data-dir="$HOME/.config/amazon-refund-chrome" \
  --no-first-run \
  "https://www.amazon.com" &

echo "Chrome 已启动，请在浏览器中登录 Amazon"
echo "登录完成后，运行: python -m src.cli collect"
```

**Patchright CDP 连接代码：**

```python
# src/browser/connection.py
from patchright.sync_api import sync_playwright
from src.config import settings

class BrowserManager:
    """通过 CDP 连接到用户已登录的 Chrome 浏览器"""

    def __init__(self):
        self._playwright = None
        self._browser = None

    def connect(self) -> "Browser":
        """连接到已运行的 Chrome 实例"""
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.connect_over_cdp(
            endpoint_url=f"http://localhost:{settings.cdp_port}",
            timeout=10000
        )
        return self._browser

    def get_page(self, url_pattern: str = "amazon.com"):
        """获取匹配 URL 的已有页面，或新建页面"""
        contexts = self._browser.contexts
        for ctx in contexts:
            for page in ctx.pages:
                if url_pattern in page.url:
                    return page
        # 没有匹配页面，在第一个 context 中新建
        return contexts[0].new_page()

    def new_page(self):
        """在已有 context 中新建页面"""
        return self._browser.contexts[0].new_page()

    def close(self):
        """断开连接（不关闭浏览器）"""
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
```

**关键点：**
- Patchright 是 Playwright 的 drop-in 替换，只需改 import：`from patchright.sync_api` 代替 `from playwright.sync_api`
- `connect_over_cdp()` 连接已有浏览器，不会创建新实例
- 用户已登录的 session/cookie 完全保留
- Patchright 自动处理反检测（禁用 `Runtime.enable` 泄露、移除自动化标志等）

### 4.2 可选方案 — Chrome DevTools MCP

Chrome DevTools MCP 是 Google 官方推出的 MCP server，可让 Claude Code 直接操控浏览器。适合**开发调试阶段**使用：

```bash
# 安装到 Claude Code
claude mcp add chrome-devtools --scope user npx chrome-devtools-mcp@latest
```

提供 29 个工具：`click`, `fill`, `navigate_page`, `take_screenshot`, `evaluate_script` 等。
可在开发过程中用于：验证选择器是否正确、调试页面解析逻辑、查看网络请求。

**注意：** MCP 适合辅助开发，不适合作为生产运行时方案。生产环境仍用 Patchright CDP。

### 4.3 Oracle DB (OCI) — python-oracledb

**连接配置：**

```python
# src/db/connection.py
import oracledb
from src.config import settings

class Database:
    """Oracle DB 连接管理（Thin 模式，无需 Oracle Client）"""

    def __init__(self):
        self._pool = None

    def init_pool(self):
        """初始化连接池"""
        self._pool = oracledb.create_pool(
            user=settings.db_user,
            password=settings.db_password,
            dsn=settings.db_dsn,
            min=2,
            max=5,
            increment=1,
            # 如果使用 OCI Autonomous DB 的 Wallet
            config_dir=settings.db_wallet_dir,       # 可选
            wallet_location=settings.db_wallet_dir,   # 可选
            wallet_password=settings.db_wallet_password  # 可选
        )

    def get_connection(self):
        return self._pool.acquire()

    def close(self):
        if self._pool:
            self._pool.close()

db = Database()
```

**数据模型 — DDL：**

```sql
-- scripts/init_db.sql

-- 订单表
CREATE TABLE orders (
    order_id        VARCHAR2(50) PRIMARY KEY,
    order_date      DATE NOT NULL,
    total_amount    NUMBER(10,2),
    status          VARCHAR2(50),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 商品表
CREATE TABLE items (
    item_id         NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id        VARCHAR2(50) NOT NULL REFERENCES orders(order_id),
    asin            VARCHAR2(20) NOT NULL,
    title           VARCHAR2(500),
    purchase_price  NUMBER(10,2) NOT NULL,
    product_url     VARCHAR2(2000),
    seller          VARCHAR2(200),        -- "Amazon.com" or 第三方
    is_eligible     NUMBER(1) DEFAULT 1,  -- 是否符合退款条件
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 价格历史表
CREATE TABLE price_history (
    history_id      NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    asin            VARCHAR2(20) NOT NULL,
    price           NUMBER(10,2) NOT NULL,
    extraction_method VARCHAR2(20),       -- 'jsonld','css','regex','llm'
    checked_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 退款记录表
CREATE TABLE refund_requests (
    refund_id       NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_id         NUMBER NOT NULL REFERENCES items(item_id),
    purchase_price  NUMBER(10,2) NOT NULL,
    current_price   NUMBER(10,2) NOT NULL,
    price_diff      NUMBER(10,2) NOT NULL,
    status          VARCHAR2(20) DEFAULT 'pending',  -- pending/in_progress/success/failed/skipped
    refund_amount   NUMBER(10,2),
    refund_type     VARCHAR2(50),         -- 'credit_card','gift_card','promotional_credit'
    conversation_log CLOB,               -- JSON 格式对话记录
    failure_reason  VARCHAR2(500),
    attempted_at    TIMESTAMP,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 系统状态表
CREATE TABLE system_state (
    key             VARCHAR2(100) PRIMARY KEY,
    value           VARCHAR2(4000),
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX idx_items_asin ON items(asin);
CREATE INDEX idx_items_order ON items(order_id);
CREATE INDEX idx_price_history_asin ON price_history(asin);
CREATE INDEX idx_price_history_time ON price_history(checked_at);
CREATE INDEX idx_refund_status ON refund_requests(status);
```

**Python ORM 层（轻量级，不用 SQLAlchemy）：**

```python
# src/db/models.py
from dataclasses import dataclass
from datetime import datetime, date
from typing import Optional

@dataclass
class Order:
    order_id: str
    order_date: date
    total_amount: float
    status: str = "collected"

@dataclass
class Item:
    order_id: str
    asin: str
    title: str
    purchase_price: float
    product_url: str
    seller: str = ""
    is_eligible: bool = True
    item_id: Optional[int] = None

@dataclass
class PriceRecord:
    asin: str
    price: float
    extraction_method: str
    checked_at: Optional[datetime] = None

@dataclass
class RefundRequest:
    item_id: int
    purchase_price: float
    current_price: float
    price_diff: float
    status: str = "pending"
    refund_amount: Optional[float] = None
    refund_type: Optional[str] = None
    conversation_log: Optional[str] = None
    failure_reason: Optional[str] = None
```

### 4.4 Module 1 — 订单采集引擎

```python
# src/collector/order_scraper.py
import re
from datetime import datetime
from src.browser.connection import BrowserManager
from src.browser.stealth import random_delay, human_scroll
from src.db.models import Order, Item

class OrderScraper:
    """从 Amazon 订单历史页面采集订单数据"""

    ORDER_HISTORY_URL = "https://www.amazon.com/gp/your-account/order-history"

    def __init__(self, browser_mgr: BrowserManager):
        self.browser = browser_mgr
        self.page = None

    def scrape_orders(self, days: int = 90) -> list[Order]:
        """采集指定天数内的所有订单"""
        self.page = self.browser.new_page()
        orders = []

        # 导航到订单历史（选择时间范围）
        self.page.goto(f"{self.ORDER_HISTORY_URL}?timeFilter=months-3")
        random_delay(2, 4)

        while True:
            # 解析当前页面的订单
            page_orders = self._parse_order_page()
            orders.extend(page_orders)

            # 翻页
            next_btn = self.page.query_selector('li.a-last a')
            if not next_btn:
                break
            next_btn.click()
            random_delay(2, 5)
            self.page.wait_for_load_state("networkidle")

        return orders

    def _parse_order_page(self) -> list[Order]:
        """解析单页订单列表"""
        orders = []
        order_cards = self.page.query_selector_all('.order-card, .a-box-group.order')

        for card in order_cards:
            try:
                order = self._extract_order(card)
                if order:
                    orders.append(order)
            except Exception as e:
                print(f"解析订单失败: {e}")
                continue

        return orders

    def _extract_order(self, card) -> Order | None:
        """从订单卡片中提取数据"""
        # 订单号
        order_id_el = card.query_selector('.yohtmlc-order-id span.value, [data-order-id]')
        if not order_id_el:
            return None
        order_id = order_id_el.inner_text().strip()

        # 订单日期
        date_el = card.query_selector('.order-info .value')
        order_date = self._parse_date(date_el.inner_text().strip()) if date_el else None

        # 总金额
        total_el = card.query_selector('.yohtmlc-order-total .value')
        total = self._parse_price(total_el.inner_text()) if total_el else 0.0

        return Order(
            order_id=order_id,
            order_date=order_date,
            total_amount=total
        )

    def scrape_order_items(self, order_id: str) -> list[Item]:
        """采集单个订单的商品详情"""
        # 导航到订单详情页
        detail_url = f"https://www.amazon.com/gp/your-account/order-details?orderID={order_id}"
        self.page.goto(detail_url)
        random_delay(1, 3)

        items = []
        item_els = self.page.query_selector_all('.shipment .a-fixed-left-grid')

        for el in item_els:
            try:
                # ASIN 从链接中提取
                link_el = el.query_selector('a[href*="/dp/"], a[href*="/gp/product/"]')
                if not link_el:
                    continue
                href = link_el.get_attribute('href')
                asin = self._extract_asin(href)

                # 商品名
                title = link_el.inner_text().strip()

                # 价格
                price_el = el.query_selector('.a-color-price')
                price = self._parse_price(price_el.inner_text()) if price_el else 0.0

                # 卖家
                seller_el = el.query_selector('.a-size-small.a-color-secondary')
                seller = seller_el.inner_text().strip() if seller_el else ""

                items.append(Item(
                    order_id=order_id,
                    asin=asin,
                    title=title[:500],
                    purchase_price=price,
                    product_url=f"https://www.amazon.com/dp/{asin}",
                    seller=seller
                ))
            except Exception as e:
                print(f"解析商品失败: {e}")
                continue

        return items

    @staticmethod
    def _extract_asin(url: str) -> str:
        match = re.search(r'/dp/([A-Z0-9]{10})', url) or \
                re.search(r'/gp/product/([A-Z0-9]{10})', url)
        return match.group(1) if match else ""

    @staticmethod
    def _parse_price(text: str) -> float:
        match = re.search(r'\$?([\d,]+\.?\d*)', text)
        return float(match.group(1).replace(',', '')) if match else 0.0

    @staticmethod
    def _parse_date(text: str) -> date:
        for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        return None
```

### 4.5 Module 2 — 价格提取 (4种策略 + 投票)

```python
# src/monitor/extractors/jsonld.py
import json

class JsonLdExtractor:
    """从 JSON-LD schema.org 结构化数据提取价格"""

    def extract(self, page) -> float | None:
        scripts = page.query_selector_all('script[type="application/ld+json"]')
        for script in scripts:
            try:
                data = json.loads(script.inner_text())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") == "Product":
                        offers = item.get("offers", {})
                        if isinstance(offers, list):
                            offers = offers[0]
                        price = offers.get("price") or offers.get("lowPrice")
                        if price:
                            return float(price)
            except (json.JSONDecodeError, ValueError, KeyError):
                continue
        return None
```

```python
# src/monitor/extractors/css_selector.py

class CssSelectorExtractor:
    """Amazon 专用 CSS 选择器提取价格"""

    # Amazon 价格元素选择器，按优先级排列
    SELECTORS = [
        "#corePrice_feature_div .a-price .a-offscreen",
        "#priceblock_ourprice",
        "#priceblock_dealprice",
        "#priceblock_saleprice",
        "#price_inside_buybox",
        "#newBuyBoxPrice",
        "span.a-price > span.a-offscreen",
        "#apex_desktop .a-price .a-offscreen",
    ]

    def extract(self, page) -> float | None:
        for selector in self.SELECTORS:
            el = page.query_selector(selector)
            if el:
                text = el.inner_text().strip()
                price = self._parse(text)
                if price and price > 0:
                    return price
        return None

    @staticmethod
    def _parse(text: str) -> float | None:
        import re
        match = re.search(r'\$?([\d,]+\.?\d*)', text)
        return float(match.group(1).replace(',', '')) if match else None
```

```python
# src/monitor/extractors/regex.py
import re

class RegexExtractor:
    """通用正则表达式价格提取"""

    PATTERNS = [
        r'"priceAmount"\s*:\s*"?([\d.]+)"?',
        r'"price"\s*:\s*"?\$?([\d,.]+)"?',
        r'class="a-price-whole"[^>]*>([\d,]+)</span>.*?class="a-price-fraction"[^>]*>(\d+)',
    ]

    def extract(self, page) -> float | None:
        content = page.content()
        for pattern in self.PATTERNS:
            match = re.search(pattern, content)
            if match:
                if len(match.groups()) == 2:  # whole + fraction
                    return float(f"{match.group(1).replace(',', '')}.{match.group(2)}")
                price = float(match.group(1).replace(',', ''))
                if 0 < price < 100000:  # 合理范围检查
                    return price
        return None
```

```python
# src/monitor/extractors/llm.py
from src.config import settings

class LlmExtractor:
    """LLM fallback 价格提取"""

    PROMPT = """Extract the current selling price from this Amazon product page text.
Return ONLY the numeric price (e.g., 29.99). If no price found, return "NONE".

Page text (truncated):
{text}"""

    def extract(self, page) -> float | None:
        # 获取页面可见文本（截取前 3000 字符）
        text = page.inner_text("body")[:3000]

        if settings.llm_provider == "ollama":
            return self._query_ollama(text)
        elif settings.llm_provider == "anthropic":
            return self._query_anthropic(text)
        elif settings.llm_provider == "openai":
            return self._query_openai(text)
        return None

    def _query_ollama(self, text: str) -> float | None:
        import httpx
        resp = httpx.post(
            f"{settings.ollama_url}/api/generate",
            json={
                "model": settings.ollama_model,
                "prompt": self.PROMPT.format(text=text),
                "stream": False,
            },
            timeout=30,
        )
        result = resp.json().get("response", "").strip()
        try:
            return float(result) if result != "NONE" else None
        except ValueError:
            return None

    def _query_anthropic(self, text: str) -> float | None:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=50,
            messages=[{"role": "user", "content": self.PROMPT.format(text=text)}],
        )
        result = msg.content[0].text.strip()
        try:
            return float(result) if result != "NONE" else None
        except ValueError:
            return None

    def _query_openai(self, text: str) -> float | None:
        import openai
        client = openai.OpenAI(api_key=settings.openai_api_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": self.PROMPT.format(text=text)}],
            max_tokens=50,
        )
        result = resp.choices[0].message.content.strip()
        try:
            return float(result) if result != "NONE" else None
        except ValueError:
            return None
```

```python
# src/monitor/voter.py
from collections import Counter
from typing import Optional

class PriceVoter:
    """4种提取方式投票决策"""

    TOLERANCE = 0.02  # 价格差异容忍度 (2 cents)

    def vote(self, prices: dict[str, Optional[float]]) -> Optional[float]:
        """
        输入: {"jsonld": 29.99, "css": 29.99, "regex": 30.01, "llm": 29.99}
        输出: 投票后的最终价格
        """
        valid = {k: v for k, v in prices.items() if v is not None}
        if not valid:
            return None

        if len(valid) == 1:
            return list(valid.values())[0]

        # 按价格分组（容忍 ±2 cents）
        values = list(valid.values())
        groups = []
        for v in values:
            placed = False
            for g in groups:
                if abs(g[0] - v) <= self.TOLERANCE:
                    g.append(v)
                    placed = True
                    break
            if not placed:
                groups.append([v])

        # 取最大组的平均值
        groups.sort(key=len, reverse=True)
        best_group = groups[0]

        # 至少需要 2 票一致（如果有 3+ 种方式返回结果）
        if len(valid) >= 3 and len(best_group) < 2:
            return None  # 无共识，标记需人工检查

        return round(sum(best_group) / len(best_group), 2)
```

### 4.6 Module 3 — 降价分析决策器

```python
# src/analyzer/price_drop.py
from dataclasses import dataclass
from src.config import settings
from src.db.models import Item, RefundRequest

@dataclass
class PriceDropResult:
    item: Item
    current_price: float
    price_diff: float
    pct_drop: float

class PriceDropAnalyzer:
    """分析降价并生成退款队列"""

    def analyze(self, item: Item, current_price: float) -> PriceDropResult | None:
        """判断是否符合退款条件"""
        if current_price >= item.purchase_price:
            return None

        diff = round(item.purchase_price - current_price, 2)
        pct = round(diff / item.purchase_price * 100, 1)

        # 过滤规则
        if diff < settings.min_refund_amount:        # 默认 $2
            return None
        if pct < settings.min_refund_pct:             # 默认 5%
            return None
        if settings.amazon_only and "amazon" not in item.seller.lower():
            return None

        return PriceDropResult(
            item=item,
            current_price=current_price,
            price_diff=diff,
            pct_drop=pct
        )

    def build_refund_queue(self, drops: list[PriceDropResult]) -> list[RefundRequest]:
        """按差价金额排序，生成退款队列"""
        drops.sort(key=lambda d: d.price_diff, reverse=True)
        return [
            RefundRequest(
                item_id=d.item.item_id,
                purchase_price=d.item.purchase_price,
                current_price=d.current_price,
                price_diff=d.price_diff,
            )
            for d in drops
        ]
```

### 4.7 Module 4 — AI 客服对话引擎

```python
# src/refund/prompts.py

SYSTEM_PROMPT = """You are helping a customer contact Amazon customer service about a price drop on a recent purchase.

Rules:
- Be polite, concise, and natural — sound like a regular customer, not a bot
- Never mention automation, scripts, or AI
- Stick to facts: order number, item name, price difference
- Accept gift card / promotional credit if direct refund is refused
- If refused twice, politely request transfer to a supervisor
- Maximum 10 messages, then gracefully exit

Context:
- Order ID: {order_id}
- Item: {item_title}
- Purchase Price: ${purchase_price:.2f}
- Current Price: ${current_price:.2f}
- Price Difference: ${price_diff:.2f}
"""

def build_opening_message(order_id: str, title: str, purchase_price: float,
                          current_price: float, price_diff: float) -> str:
    return (
        f"Hi, I recently purchased {title} (Order #{order_id}) for ${purchase_price:.2f}. "
        f"I noticed the price has dropped to ${current_price:.2f} — a ${price_diff:.2f} difference. "
        f"Would it be possible to get an adjustment or refund for the price difference?"
    )
```

```python
# src/refund/strategy.py
from enum import Enum, auto

class RefundState(Enum):
    OPENING = auto()       # 初始开场
    WAITING = auto()       # 等待客服回复
    NEGOTIATING = auto()   # 协商中
    ESCALATING = auto()    # 请求转接
    COMPLETED = auto()     # 成功
    FAILED = auto()        # 失败
    TIMEOUT = auto()       # 超时

class RefundStrategy:
    MAX_ROUNDS = 10

    def __init__(self):
        self.state = RefundState.OPENING
        self.round = 0
        self.messages: list[dict] = []

    def should_continue(self) -> bool:
        return self.state not in (
            RefundState.COMPLETED,
            RefundState.FAILED,
            RefundState.TIMEOUT
        ) and self.round < self.MAX_ROUNDS

    def record_message(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})
        if role == "user":  # 我们发送的消息
            self.round += 1

    def detect_outcome(self, cs_message: str) -> RefundState:
        """分析客服回复，判断对话状态"""
        lower = cs_message.lower()

        # 成功信号
        success_keywords = ["refund", "credit", "adjusted", "applied",
                          "processed", "issued", "courtesy"]
        if any(k in lower for k in success_keywords):
            self.state = RefundState.COMPLETED
            return self.state

        # 拒绝信号
        reject_keywords = ["unable", "cannot", "not eligible", "not possible",
                          "policy", "unfortunately"]
        if any(k in lower for k in reject_keywords):
            if self.state == RefundState.ESCALATING:
                self.state = RefundState.FAILED
            else:
                self.state = RefundState.ESCALATING
            return self.state

        # 安全信号 — 立即停止
        safety_keywords = ["verify your identity", "suspicious", "unusual activity",
                          "security", "locked"]
        if any(k in lower for k in safety_keywords):
            self.state = RefundState.FAILED
            return self.state

        self.state = RefundState.NEGOTIATING
        return self.state
```

```python
# src/refund/chat_agent.py
from src.browser.connection import BrowserManager
from src.browser.stealth import random_delay, human_type
from src.refund.strategy import RefundStrategy, RefundState
from src.refund.prompts import SYSTEM_PROMPT, build_opening_message
from src.config import settings

class ChatAgent:
    """AI 驱动的客服对话代理"""

    CS_CHAT_URL = "https://www.amazon.com/gp/help/customer/contact-us"

    def __init__(self, browser_mgr: BrowserManager, llm_client):
        self.browser = browser_mgr
        self.llm = llm_client
        self.strategy = RefundStrategy()

    def execute_refund(self, order_id: str, title: str,
                       purchase_price: float, current_price: float,
                       price_diff: float) -> dict:
        """执行完整的退款对话流程"""
        page = self.browser.new_page()

        try:
            # 1. 导航到客服页面并打开聊天
            self._open_chat(page, order_id)

            # 2. 发送开场白
            opening = build_opening_message(
                order_id, title, purchase_price, current_price, price_diff
            )
            self._send_message(page, opening)
            self.strategy.record_message("user", opening)

            # 3. 对话循环
            while self.strategy.should_continue():
                # 等待客服回复
                cs_reply = self._wait_for_reply(page)
                if not cs_reply:
                    self.strategy.state = RefundState.TIMEOUT
                    break

                self.strategy.record_message("assistant", cs_reply)
                outcome = self.strategy.detect_outcome(cs_reply)

                if outcome == RefundState.COMPLETED:
                    break
                if outcome == RefundState.FAILED:
                    break

                # 用 LLM 生成回复
                reply = self._generate_reply(
                    order_id, title, purchase_price, current_price, price_diff
                )
                self._send_message(page, reply)
                self.strategy.record_message("user", reply)

            return {
                "status": self.strategy.state.name.lower(),
                "rounds": self.strategy.round,
                "messages": self.strategy.messages,
            }

        finally:
            page.close()

    def _open_chat(self, page, order_id: str):
        """导航到客服聊天（需要根据 Amazon UI 调整选择器）"""
        page.goto(self.CS_CHAT_URL)
        random_delay(2, 4)
        # Amazon 客服页面导航逻辑（选择订单 → 选择问题类型 → 开始聊天）
        # 这部分选择器需要根据实际页面调整
        # ...

    def _send_message(self, page, text: str):
        """在聊天窗口中输入并发送消息"""
        input_box = page.wait_for_selector(
            'textarea[placeholder*="Type"], input[type="text"]',
            timeout=10000
        )
        human_type(input_box, text)
        random_delay(0.5, 1)
        send_btn = page.query_selector('button[type="submit"], .send-button')
        if send_btn:
            send_btn.click()

    def _wait_for_reply(self, page, timeout: int = 60) -> str | None:
        """等待客服回复"""
        try:
            # 等待新消息出现（选择器需根据实际聊天 UI 调整）
            page.wait_for_selector(
                '.cs-message:last-child, .agent-message:last-child',
                timeout=timeout * 1000
            )
            random_delay(1, 2)
            msgs = page.query_selector_all('.cs-message, .agent-message')
            return msgs[-1].inner_text().strip() if msgs else None
        except Exception:
            return None

    def _generate_reply(self, order_id, title, purchase_price,
                        current_price, price_diff) -> str:
        """用 LLM 生成上下文感知的回复"""
        system = SYSTEM_PROMPT.format(
            order_id=order_id,
            item_title=title,
            purchase_price=purchase_price,
            current_price=current_price,
            price_diff=price_diff,
        )
        messages = [{"role": "system", "content": system}]
        messages.extend(self.strategy.messages)
        messages.append({
            "role": "user",
            "content": "Generate the next customer message. Keep it brief and natural."
        })
        return self.llm.chat(messages)
```

### 4.8 人类行为模拟

```python
# src/browser/stealth.py
import random
import time

def random_delay(min_sec: float = 1.0, max_sec: float = 3.0):
    """随机延迟，模拟人类操作节奏"""
    time.sleep(random.uniform(min_sec, max_sec))

def human_type(element, text: str, min_delay: int = 50, max_delay: int = 150):
    """模拟人类打字速度"""
    for char in text:
        element.type(char, delay=random.randint(min_delay, max_delay))

def human_scroll(page, direction: str = "down", amount: int = None):
    """模拟人类滚动"""
    if amount is None:
        amount = random.randint(200, 600)
    delta = amount if direction == "down" else -amount
    page.mouse.wheel(0, delta)
    random_delay(0.3, 1.0)

def jittered_interval(base_seconds: float, jitter_pct: float = 0.3) -> float:
    """添加 ±30% 抖动的时间间隔"""
    jitter = base_seconds * jitter_pct
    return base_seconds + random.uniform(-jitter, jitter)
```

### 4.9 配置管理

```python
# src/config.py
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # Chrome CDP
    cdp_port: int = 9222

    # Oracle DB
    db_user: str = ""
    db_password: str = ""
    db_dsn: str = ""              # e.g., "host:port/service_name"
    db_wallet_dir: Optional[str] = None
    db_wallet_password: Optional[str] = None

    # LLM
    llm_provider: str = "ollama"   # ollama / anthropic / openai
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:8b"
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None

    # 退款规则
    min_refund_amount: float = 2.0       # 最小退款金额 $
    min_refund_pct: float = 5.0          # 最小降价百分比 %
    amazon_only: bool = True             # 只处理 Amazon 自营
    max_daily_refunds: int = 5           # 每日最多退款请求数
    max_chat_rounds: int = 10            # 单次对话最大轮数

    # 价格检查
    check_interval_hours: float = 6.0    # 价格检查间隔（小时）
    interval_jitter_pct: float = 0.3     # 间隔抖动百分比

    # 通知
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    ntfy_topic: Optional[str] = None
    ntfy_server: str = "https://ntfy.sh"

    model_config = {"env_file": ".env", "env_prefix": "AR_"}

settings = Settings()
```

### 4.10 CLI 入口

```python
# src/cli.py
import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Amazon Price Track & Auto Refund Tool")
console = Console()

@app.command()
def collect(days: int = typer.Option(90, help="采集最近 N 天的订单")):
    """采集 Amazon 订单历史"""
    from src.browser.connection import BrowserManager
    from src.collector.order_scraper import OrderScraper
    from src.db.connection import db

    db.init_pool()
    mgr = BrowserManager()
    mgr.connect()

    scraper = OrderScraper(mgr)
    orders = scraper.scrape_orders(days=days)
    console.print(f"采集到 {len(orders)} 个订单")

    for order in orders:
        items = scraper.scrape_order_items(order.order_id)
        # 存入数据库...
        console.print(f"  订单 {order.order_id}: {len(items)} 件商品")

    mgr.close()
    db.close()

@app.command()
def check():
    """检查所有商品当前价格"""
    console.print("正在检查价格...")
    # 实现价格检查逻辑

@app.command()
def analyze():
    """分析降价情况并显示退款机会"""
    # 实现降价分析逻辑

@app.command()
def refund(order_id: str = typer.Argument(None, help="指定订单号，不指定则处理队列")):
    """执行 AI 自动退款对话"""
    # 实现退款逻辑

@app.command()
def status():
    """显示系统状态和统计"""
    # 实现状态显示

@app.command()
def init_db():
    """初始化数据库表结构"""
    from src.db.connection import db
    from src.db.migrations import create_tables

    db.init_pool()
    create_tables(db)
    console.print("数据库表创建成功")
    db.close()

if __name__ == "__main__":
    app()
```

---

## 五、依赖清单

```toml
# pyproject.toml
[project]
name = "amazon-refund"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "patchright>=1.58",        # 浏览器自动化（反检测）
    "oracledb>=3.0",           # Oracle DB 驱动（Thin 模式）
    "pydantic-settings>=2.0",  # 配置管理
    "typer[all]>=0.12",        # CLI 框架
    "rich>=13.0",              # 终端美化输出
    "apscheduler>=3.10",       # 任务调度
    "httpx>=0.27",             # HTTP 客户端（Ollama 调用）
]

[project.optional-dependencies]
anthropic = ["anthropic>=1.0"]
openai = ["openai>=1.0"]
notify = [
    "python-telegram-bot>=21.0",
]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-mock>=3.12",
    "ruff>=0.4",
]

[project.scripts]
ar = "src.cli:app"
```

---

## 六、测试方案

### 6.1 测试分层

| 层级 | 范围 | 方式 | 依赖 |
|------|------|------|------|
| **L1 单元测试** | 解析器、投票器、分析器 | pytest + 固定 HTML fixtures | 无外部依赖 |
| **L2 数据库测试** | CRUD、迁移 | pytest + 真实 Oracle DB | OCI 数据库 |
| **L3 浏览器集成** | 页面导航、元素选择 | pytest + Patchright + 本地 HTML | 无需 Amazon |
| **L4 端到端** | 完整流程 | 手动/半自动，连接真实 Amazon | CDP + 真实账号 |

### 6.2 L1 — 单元测试（无外部依赖）

```python
# tests/conftest.py
import pytest
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"

@pytest.fixture
def order_page_html():
    return (FIXTURES_DIR / "order_page.html").read_text()

@pytest.fixture
def product_page_html():
    return (FIXTURES_DIR / "product_page.html").read_text()
```

```python
# tests/test_extractors.py
"""测试价格提取器 — 用保存的 HTML 样本"""

def test_jsonld_extracts_price(product_page_html):
    """JSON-LD 应正确提取 schema.org 价格"""
    # 需要用 mock page 对象
    # ...

def test_css_selector_extracts_price(product_page_html):
    """CSS 选择器应提取 Amazon 价格元素"""
    # ...

def test_regex_extracts_price(product_page_html):
    """正则表达式应从页面源码提取价格"""
    # ...
```

```python
# tests/test_voter.py
from src.monitor.voter import PriceVoter

def test_unanimous_vote():
    voter = PriceVoter()
    result = voter.vote({"jsonld": 29.99, "css": 29.99, "regex": 29.99, "llm": 29.99})
    assert result == 29.99

def test_majority_vote():
    voter = PriceVoter()
    result = voter.vote({"jsonld": 29.99, "css": 29.99, "regex": 35.00, "llm": 29.99})
    assert result == 29.99

def test_no_consensus():
    voter = PriceVoter()
    result = voter.vote({"jsonld": 29.99, "css": 35.00, "regex": 42.00, "llm": None})
    assert result is None  # 无共识

def test_tolerance():
    voter = PriceVoter()
    result = voter.vote({"jsonld": 29.99, "css": 30.00, "regex": 29.98, "llm": None})
    assert abs(result - 29.99) < 0.02

def test_single_result():
    voter = PriceVoter()
    result = voter.vote({"jsonld": None, "css": 25.00, "regex": None, "llm": None})
    assert result == 25.00

def test_all_none():
    voter = PriceVoter()
    result = voter.vote({"jsonld": None, "css": None, "regex": None, "llm": None})
    assert result is None
```

```python
# tests/test_price_drop.py
from src.analyzer.price_drop import PriceDropAnalyzer
from src.db.models import Item

def test_detects_significant_drop():
    analyzer = PriceDropAnalyzer()
    item = Item(order_id="111", asin="B000TEST", title="Test",
                purchase_price=100.0, product_url="", seller="Amazon.com")
    result = analyzer.analyze(item, current_price=80.0)
    assert result is not None
    assert result.price_diff == 20.0
    assert result.pct_drop == 20.0

def test_ignores_small_drop():
    analyzer = PriceDropAnalyzer()
    item = Item(order_id="111", asin="B000TEST", title="Test",
                purchase_price=100.0, product_url="", seller="Amazon.com")
    result = analyzer.analyze(item, current_price=99.50)
    assert result is None  # $0.50 < $2 阈值

def test_ignores_price_increase():
    analyzer = PriceDropAnalyzer()
    item = Item(order_id="111", asin="B000TEST", title="Test",
                purchase_price=100.0, product_url="", seller="Amazon.com")
    result = analyzer.analyze(item, current_price=110.0)
    assert result is None

def test_ignores_third_party_seller():
    analyzer = PriceDropAnalyzer()
    item = Item(order_id="111", asin="B000TEST", title="Test",
                purchase_price=100.0, product_url="", seller="RandomSeller LLC")
    result = analyzer.analyze(item, current_price=70.0)
    assert result is None  # amazon_only=True
```

```python
# tests/test_strategy.py
from src.refund.strategy import RefundStrategy, RefundState

def test_detects_success():
    s = RefundStrategy()
    state = s.detect_outcome("I've issued a $5.00 refund to your credit card.")
    assert state == RefundState.COMPLETED

def test_detects_rejection_then_escalation():
    s = RefundStrategy()
    state = s.detect_outcome("Unfortunately, we're unable to process that request.")
    assert state == RefundState.ESCALATING

def test_detects_final_rejection():
    s = RefundStrategy()
    s.state = RefundState.ESCALATING
    state = s.detect_outcome("I'm sorry, it's not possible to adjust the price.")
    assert state == RefundState.FAILED

def test_detects_safety_signal():
    s = RefundStrategy()
    state = s.detect_outcome("For your security, please verify your identity.")
    assert state == RefundState.FAILED

def test_max_rounds():
    s = RefundStrategy()
    for i in range(10):
        s.record_message("user", f"message {i}")
    assert not s.should_continue()
```

### 6.3 L2 — 数据库测试

```python
# tests/test_db.py
import pytest
import oracledb
from src.db.connection import db

@pytest.fixture(scope="session")
def db_connection():
    """使用真实 Oracle DB，测试前后清理数据"""
    db.init_pool()
    conn = db.get_connection()
    yield conn
    # 清理测试数据
    with conn.cursor() as cur:
        cur.execute("DELETE FROM refund_requests WHERE 1=1")
        cur.execute("DELETE FROM price_history WHERE 1=1")
        cur.execute("DELETE FROM items WHERE asin LIKE 'TEST%'")
        cur.execute("DELETE FROM orders WHERE order_id LIKE 'TEST%'")
    conn.commit()
    conn.close()
    db.close()

def test_insert_and_query_order(db_connection):
    conn = db_connection
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO orders (order_id, order_date, total_amount, status)
            VALUES ('TEST-001', DATE '2026-01-15', 99.99, 'collected')
        """)
        conn.commit()
        cur.execute("SELECT * FROM orders WHERE order_id = 'TEST-001'")
        row = cur.fetchone()
        assert row is not None
        assert row[0] == 'TEST-001'

def test_price_history_insert(db_connection):
    conn = db_connection
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO price_history (asin, price, extraction_method)
            VALUES ('TESTASIN01', 49.99, 'css')
        """)
        conn.commit()
        cur.execute("""
            SELECT price FROM price_history
            WHERE asin = 'TESTASIN01' ORDER BY checked_at DESC
        """)
        row = cur.fetchone()
        assert row[0] == 49.99
```

### 6.4 L3 — 浏览器集成测试（本地 HTML）

```python
# tests/test_browser_integration.py
import pytest
from patchright.sync_api import sync_playwright
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"

@pytest.fixture(scope="module")
def browser():
    """启动独立 Patchright 浏览器（非 CDP，测试用）"""
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    yield browser
    browser.close()
    pw.stop()

@pytest.fixture
def page(browser):
    page = browser.new_page()
    yield page
    page.close()

def test_css_extractor_on_real_html(page):
    """用保存的 Amazon 产品页面 HTML 测试 CSS 提取"""
    html_path = FIXTURES_DIR / "product_page.html"
    page.goto(f"file://{html_path}")
    from src.monitor.extractors.css_selector import CssSelectorExtractor
    extractor = CssSelectorExtractor()
    price = extractor.extract(page)
    assert price is not None
    assert price > 0

def test_jsonld_extractor_on_real_html(page):
    """测试 JSON-LD 提取"""
    html_path = FIXTURES_DIR / "product_page.html"
    page.goto(f"file://{html_path}")
    from src.monitor.extractors.jsonld import JsonLdExtractor
    extractor = JsonLdExtractor()
    price = extractor.extract(page)
    # JSON-LD 可能不存在于所有页面
    # assert price is None or price > 0
```

### 6.5 L4 — 端到端测试（手动/半自动）

端到端测试需要连接真实 Amazon，应在开发者手动监督下运行：

```python
# tests/e2e/test_full_flow.py
"""
端到端测试 — 需要：
1. Chrome 已启动并带 --remote-debugging-port=9222
2. 用户已在 Chrome 中登录 Amazon
3. Oracle DB 已配置
4. 运行: pytest tests/e2e/ -v --manual
"""
import pytest

@pytest.mark.manual
def test_collect_orders():
    """验证订单采集流程"""
    from src.browser.connection import BrowserManager
    from src.collector.order_scraper import OrderScraper

    mgr = BrowserManager()
    mgr.connect()
    scraper = OrderScraper(mgr)
    orders = scraper.scrape_orders(days=30)
    assert len(orders) > 0
    print(f"采集到 {len(orders)} 个订单")
    for o in orders[:3]:
        print(f"  {o.order_id} - {o.order_date} - ${o.total_amount}")
    mgr.close()

@pytest.mark.manual
def test_check_price():
    """验证价格检查流程"""
    from src.browser.connection import BrowserManager
    from src.monitor.price_checker import PriceChecker

    mgr = BrowserManager()
    mgr.connect()
    checker = PriceChecker(mgr)
    # 用一个已知 ASIN 测试
    price = checker.check_price("B0D1XD1ZV3")  # 替换为实际 ASIN
    print(f"当前价格: ${price}")
    assert price is not None
    mgr.close()
```

### 6.6 测试运行命令

```bash
# 运行所有单元测试（L1，无外部依赖）
pytest tests/ -v --ignore=tests/e2e/ -k "not db"

# 运行数据库测试（L2，需要 Oracle DB）
pytest tests/test_db.py -v

# 运行浏览器集成测试（L3，需要 Patchright 安装）
pytest tests/test_browser_integration.py -v

# 运行端到端测试（L4，需要 Chrome + Amazon 登录）
pytest tests/e2e/ -v -m manual

# 运行全部 + 覆盖率
pytest tests/ --ignore=tests/e2e/ --cov=src --cov-report=term-missing
```

### 6.7 测试 Fixtures 准备

需要手动保存以下 HTML 样本到 `tests/fixtures/`：

1. **order_page.html** — 从 Amazon 订单历史页面保存（`Ctrl+S`），用于测试订单解析
2. **product_page.html** — 从任意 Amazon 商品页面保存，用于测试价格提取
3. **chat_page.html** — 从 Amazon 客服聊天页面保存，用于测试聊天 UI 交互

```bash
# 快速保存页面的脚本（在已连接的 Chrome 中执行）
python -c "
from patchright.sync_api import sync_playwright
pw = sync_playwright().start()
browser = pw.chromium.connect_over_cdp('http://localhost:9222')
page = browser.contexts[0].pages[0]
page.goto('https://www.amazon.com/gp/your-account/order-history')
import time; time.sleep(3)
with open('tests/fixtures/order_page.html', 'w') as f:
    f.write(page.content())
print('已保存 order_page.html')
browser.close()
pw.stop()
"
```

---

## 七、开发阶段计划（调整后）

### Phase 1：MVP — 订单采集 + 价格检查 (CLI)

**目标：** 通过命令行能采集订单、检查价格、显示降价

**任务清单：**
1. 项目初始化：pyproject.toml、.env、.gitignore
2. `src/config.py` — Pydantic Settings 配置
3. `src/browser/connection.py` — CDP 连接
4. `src/browser/stealth.py` — 人类行为模拟
5. `src/db/` — Oracle DB 连接、DDL 迁移
6. `src/collector/` — 订单采集
7. `src/monitor/extractors/` — 4 种价格提取器
8. `src/monitor/voter.py` — 投票器
9. `src/analyzer/price_drop.py` — 降价分析
10. `src/cli.py` — CLI 入口 (`collect`, `check`, `analyze`, `init-db`)
11. L1 + L2 测试
12. 保存 HTML fixtures 并验证解析器

**验收标准：**
- `ar init-db` 创建数据库表
- `ar collect` 采集订单并入库
- `ar check` 检查价格并记录
- `ar analyze` 输出降价商品列表

### Phase 2：AI 退款 + 通知

**目标：** AI 客服对话完成退款，降价/退款结果通知

**任务清单：**
1. `src/refund/prompts.py` — 提示词模板
2. `src/refund/strategy.py` — 对话策略状态机
3. `src/refund/chat_agent.py` — 聊天自动化
4. `src/notify/` — Telegram / ntfy 通知
5. `src/cli.py` 添加 `refund` 命令
6. APScheduler 定时任务集成
7. 对话日志存储和查询
8. L4 端到端测试

**验收标准：**
- `ar refund` 自动完成一次退款对话
- 降价和退款结果通过 Telegram 通知

---

## 八、关键注意事项

### 8.1 Amazon 选择器维护

Amazon 页面结构会频繁变化。建议：
- 选择器定义集中在常量/配置中，便于快速更新
- 保存成功解析的 HTML 样本作为回归测试 fixture
- 价格提取的 4 路投票机制本身就是容错设计

### 8.2 安全限制（硬编码）

以下限制应硬编码，不可通过配置覆盖：
- 单次对话最多 **10 轮**
- 每日最多 **5 次**退款请求
- 连续 **3 次**失败后暂停 **24 小时**
- 遇到安全/身份验证提示**立即停止**

### 8.3 Patchright vs Playwright 注意

- Patchright **仅支持 Chromium**，不支持 Firefox/WebKit
- API 完全兼容 Playwright，只需改 import
- 如果遇到 Patchright 特有 bug，可回退到 Playwright（改一行 import）
- `isolated_context=True` 是 Patchright 独有参数，用于更安全的 JS 执行

### 8.4 Oracle DB Thin vs Thick 模式

默认用 **Thin 模式**（无需安装 Oracle Client）：
- 支持 Oracle 12c 及以上
- 如果 OCI 使用 Autonomous Database + Wallet，需要配置 `db_wallet_dir` 和 `db_wallet_password`
- DSN 格式：`host:port/service_name` 或 TNS 名称
