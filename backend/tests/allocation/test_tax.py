"""Tests for the single sales-tax calculation function — ADR-0029.

calculate_tax works in cents (int), matching the project's existing
cents-based money convention (service.py's _to_cents/_from_cents, ADR-0002).
calculate_tax_dollars is a thin float wrapper for the two call sites
(order_service.py) not yet converted to cents — it must not duplicate the
`* TAX_RATE` formula, only delegate.
"""

from app.allocation.tax import TAX_RATE, calculate_tax, calculate_tax_dollars


def test_tax_rate_is_seven_percent():
    assert TAX_RATE == 0.07


def test_calculate_tax_applies_rate_to_subtotal_cents():
    # $100.00 subtotal -> 7% = $7.00 tax.
    assert calculate_tax(10_000) == 700


def test_calculate_tax_on_zero_subtotal_is_zero():
    assert calculate_tax(0) == 0


def test_calculate_tax_rounds_to_the_nearest_cent():
    # 1435 cents * 0.07 = 100.45 cents -> rounds to 100 cents.
    assert calculate_tax(1_435) == 100


def test_calculate_tax_rounds_the_summed_subtotal_not_per_line():
    # ADR-0029 §3: tax must be computed once on the already-summed subtotal,
    # not per line with results summed afterward -- per-line rounding
    # accumulates error across lines. Three lines of 50 cents each: summed
    # subtotal is 150 cents, so the correct tax is calculate_tax(150) = 11
    # (150 * 0.07 = 10.500000000000002, rounds to 11). Rounding per line
    # first (WRONG, not what this function does) gives calculate_tax(50) = 4
    # per line (50 * 0.07 = 3.5000000000000004, rounds to 4), summed over 3
    # lines = 12 -- diverges from the correct summed-subtotal answer.
    line_cents = [50, 50, 50]
    correct_tax = calculate_tax(sum(line_cents))
    wrong_per_line_tax = sum(calculate_tax(c) for c in line_cents)

    assert correct_tax == 11
    assert wrong_per_line_tax == 12
    assert correct_tax != wrong_per_line_tax


def test_calculate_tax_dollars_delegates_to_calculate_tax():
    assert calculate_tax_dollars(100.00) == 7.00


def test_calculate_tax_dollars_on_zero_is_zero():
    assert calculate_tax_dollars(0.0) == 0.0
