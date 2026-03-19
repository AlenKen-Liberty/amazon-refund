from __future__ import annotations

import re


class RegexExtractor:
    PATTERNS = [
        r'"priceAmount"\s*:\s*"?([\d.]+)"?',
        r'"price"\s*:\s*"?\$?([\d,.]+)"?',
        r'class="a-price-whole"[^>]*>([\d,]+)</span>.*?class="a-price-fraction"[^>]*>(\d+)',
    ]

    def extract(self, page: object) -> float | None:
        content = page.content()
        for pattern in self.PATTERNS:
            match = re.search(pattern, content, flags=re.DOTALL)
            if not match:
                continue
            if len(match.groups()) == 2:
                return float(f"{match.group(1).replace(',', '')}.{match.group(2)}")

            value = float(match.group(1).replace(",", ""))
            if 0 < value < 100000:
                return value
        return None
