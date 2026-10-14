"""Pure comparison/metric logic for AI-pipeline accuracy validation — see
ADR-0044 §3-4. No network calls, no Session: every input here is a plain
value the caller already fetched from the DB or from a model call.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.order_response_parser.client import ExtractedLine
from app.price_ingestion.matching import MatchedLine

OrderResponseCategory = Literal["correct_match", "missing", "mismatched"]


@dataclass
class OrderItemGroundTruth:
    order_item_id: uuid.UUID
    received_quantity: int | None
    confirmed_price: Decimal | None
    received_price: Decimal | None

    def ground_truth_price(self) -> Decimal | None:
        """confirmed_price wins when both are set — same preference ADR-0013/
        ADR-0027 already give it as the "final" price for this OrderItem."""
        return self.confirmed_price if self.confirmed_price is not None else self.received_price


@dataclass
class OrderResponseScore:
    order_item_id: uuid.UUID
    category: OrderResponseCategory
    price_match: bool | None
    quantity_match: bool | None


def score_order_response_item(
    ground_truth: OrderItemGroundTruth,
    extracted_lines: list[ExtractedLine],
    *,
    known_mismatched_target_ids: set[uuid.UUID] | None = None,
) -> OrderResponseScore:
    """Classifies one OrderItem's result into exactly one of three outcomes
    — see ADR-0044 §3 (deliberately not a binary match rate, to surface the
    ADR-0039 silent-wrong-match failure mode separately from a plain miss).

    known_mismatched_target_ids: order_item_id values that the caller has
    independently determined (from the mapping file + ground truth across
    the whole Order) are NOT the correct target for any extracted line that
    references them — i.e. this item's ground truth was stolen by a line
    meant for a different item. Scoring a single item in isolation cannot
    discover this on its own; it is supplied by the caller, which sees the
    whole Order.
    """
    known_mismatched_target_ids = known_mismatched_target_ids or set()

    matching_line = next(
        (
            line
            for line in extracted_lines
            if line.matched_order_item_id == ground_truth.order_item_id
        ),
        None,
    )

    if matching_line is not None:
        category: OrderResponseCategory = "correct_match"
    elif ground_truth.order_item_id in known_mismatched_target_ids:
        category = "mismatched"
    else:
        category = "missing"

    if category != "correct_match":
        return OrderResponseScore(
            order_item_id=ground_truth.order_item_id,
            category=category,
            price_match=None,
            quantity_match=None,
        )

    ground_truth_price = ground_truth.ground_truth_price()
    price_match = (
        None
        if ground_truth_price is None
        else Decimal(str(matching_line.price)) == ground_truth_price
    )
    quantity_match = (
        None
        if ground_truth.received_quantity is None
        else matching_line.quantity == ground_truth.received_quantity
    )

    return OrderResponseScore(
        order_item_id=ground_truth.order_item_id,
        category=category,
        price_match=price_match,
        quantity_match=quantity_match,
    )


def detect_mismatched_items(
    ground_truths: list[OrderItemGroundTruth], extracted_lines: list[ExtractedLine]
) -> set[uuid.UUID]:
    """Order-level algorithm distinguishing mismatched from missing — see
    ADR-0044 §3. Runs once per Order over ALL its ground-truth items and
    ALL extracted lines (a single item can't be classified in isolation:
    detecting theft requires comparing against every OTHER item's ground
    truth too).

    For a "victim" item with no line pointing at it, look at lines
    attributed to some OTHER "thief" item on the same Order. A line is
    positive numeric evidence of theft only if its price AND quantity
    match the victim's ground truth exactly AND do NOT equally match the
    thief's own ground truth — i.e. the line's numbers single out the
    victim, not just coincide with both. Any other case (no such line, or
    the numbers don't uniquely point at one candidate) stays `missing` —
    missing is the safe default, mismatched requires positive evidence,
    never a guess from text/content (see "Альтернативы" in ADR-0044).
    """
    unmatched_item_ids = {
        gt.order_item_id
        for gt in ground_truths
        if not any(line.matched_order_item_id == gt.order_item_id for line in extracted_lines)
    }
    ground_truth_by_id = {gt.order_item_id: gt for gt in ground_truths}

    def _numbers_match(line: ExtractedLine, gt: OrderItemGroundTruth) -> bool:
        gt_price = gt.ground_truth_price()
        price_matches = gt_price is not None and Decimal(str(line.price)) == gt_price
        quantity_matches = (
            gt.received_quantity is not None and line.quantity == gt.received_quantity
        )
        return price_matches and quantity_matches

    mismatched: set[uuid.UUID] = set()
    for victim_id in unmatched_item_ids:
        victim_gt = ground_truth_by_id[victim_id]
        for line in extracted_lines:
            thief_id = line.matched_order_item_id
            if thief_id is None or thief_id == victim_id or thief_id not in ground_truth_by_id:
                continue
            thief_gt = ground_truth_by_id[thief_id]
            if _numbers_match(line, victim_gt) and not _numbers_match(line, thief_gt):
                mismatched.add(victim_id)
                break

    return mismatched


def aggregate_order_response_scores(scores: list[OrderResponseScore]) -> dict:
    """Three separate rates (correct_match/missing/mismatched), never
    collapsed into one match-rate percentage — see ADR-0044 §3. Price/
    quantity accuracy are computed only over the correct_match subset (and
    only over items in that subset that actually carry a ground-truth
    value) — see ADR-0044 §4."""
    total = len(scores)

    def _rate(category: OrderResponseCategory) -> float:
        return sum(1 for s in scores if s.category == category) / total

    price_judged = [s.price_match for s in scores if s.price_match is not None]
    quantity_judged = [s.quantity_match for s in scores if s.quantity_match is not None]

    return {
        "total": total,
        "correct_match_rate": _rate("correct_match"),
        "missing_rate": _rate("missing"),
        "mismatched_rate": _rate("mismatched"),
        "price_accuracy": (sum(price_judged) / len(price_judged)) if price_judged else None,
        "price_accuracy_denominator": len(price_judged),
        "quantity_accuracy": (
            (sum(quantity_judged) / len(quantity_judged)) if quantity_judged else None
        ),
        "quantity_accuracy_denominator": len(quantity_judged),
    }


@dataclass
class DualModelComparison:
    raw_name: str
    needs_manual_review: bool
    sol_line: MatchedLine
    luna_line: MatchedLine


def compare_dual_model_lines(
    sol_lines: list[MatchedLine], luna_lines: list[MatchedLine]
) -> list[DualModelComparison]:
    """Pairs sol/luna results by position (both pipelines concatenate lines
    in document order, ADR-0021/ADR-0023) and flags disagreement — see
    ADR-0044 §5. Agreement is exact: same action, and same material_id when
    action == "match". Agreement is NOT evidence of correctness (both
    models can share the same error) — that caveat belongs in the report,
    not in this function's output."""
    return [
        DualModelComparison(
            raw_name=sol_line.extracted.raw_name,
            needs_manual_review=(
                sol_line.decision.action != luna_line.decision.action
                or sol_line.decision.material_id != luna_line.decision.material_id
            ),
            sol_line=sol_line,
            luna_line=luna_line,
        )
        for sol_line, luna_line in zip(sol_lines, luna_lines, strict=True)
    ]
