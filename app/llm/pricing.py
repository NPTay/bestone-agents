"""Model prices (USD per 1M tokens) and cost calculation."""

import logging
from dataclasses import dataclass
from decimal import Decimal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelPrice:
    input: Decimal
    output: Decimal
    cache_read: Decimal
    cache_write: Decimal


PRICES: dict[str, ModelPrice] = {
    "claude-sonnet-5-5": ModelPrice(
        Decimal("2.00"), Decimal("10.00"), Decimal("0.20"), Decimal("2.50")
    ),
    "claude-haiku-5-5": ModelPrice(
        Decimal("0.10"), Decimal("0.50"), Decimal("0.01"), Decimal("0.125")
    ),
}

_MILLION = Decimal(1_000_000)


def cost_usd(
    model: str, input_tokens: int, output_tokens: int, cache_read: int, cache_write: int
) -> Decimal:
    """Cost of one call in USD; unknown model costs 0 and logs a warning."""
    price = PRICES.get(model)
    if price is None:
        logger.warning("No price configured for model %r; cost recorded as 0", model)
        return Decimal(0)
    return (
        price.input * input_tokens
        + price.output * output_tokens
        + price.cache_read * cache_read
        + price.cache_write * cache_write
    ) / _MILLION
