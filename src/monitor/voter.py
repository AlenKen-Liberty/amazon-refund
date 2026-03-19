from __future__ import annotations


class PriceVoter:
    TOLERANCE = 0.02

    def vote(self, prices: dict[str, float | None]) -> float | None:
        valid_prices = [value for value in prices.values() if value is not None]
        if not valid_prices:
            return None
        if len(valid_prices) == 1:
            return round(valid_prices[0], 2)

        groups: list[list[float]] = []
        for value in valid_prices:
            for group in groups:
                if abs(group[0] - value) <= self.TOLERANCE:
                    group.append(value)
                    break
            else:
                groups.append([value])

        groups.sort(key=len, reverse=True)
        best_group = groups[0]

        if len(valid_prices) >= 3 and len(best_group) < 2:
            return None

        return round(sum(best_group) / len(best_group), 2)
