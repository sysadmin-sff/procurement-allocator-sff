"""CSV row building + markdown report rendering for AI-pipeline accuracy
validation — see ADR-0044 §6. Pure formatting over scores/comparisons
already computed by scoring.py; no network, no DB, no file I/O here (the
caller decides where to write).
"""

from __future__ import annotations

from app.scripts.validation.scoring import DualModelComparison, OrderResponseScore


def order_response_csv_rows(*, document: str, scores: list[OrderResponseScore]) -> list[dict]:
    """One CSV row per OrderItem with ground truth — see ADR-0044 §6. The
    manual_label column is always empty: order-response rows have a known
    category already (DB ground truth), manual labeling is not needed for
    them (unlike the price-ingestion dual-model CSV)."""
    return [
        {
            "document": document,
            "order_item_id": str(score.order_item_id),
            "category": score.category,
            "price_match": "" if score.price_match is None else str(score.price_match),
            "quantity_match": "" if score.quantity_match is None else str(score.quantity_match),
            "manual_label": "",
        }
        for score in scores
    ]


def order_response_markdown_report(aggregate: dict) -> str:
    """See ADR-0044 §3-4: three separate rates, never one match-rate
    percentage; price/quantity accuracy shown with their own denominator
    (only correct_match rows that carried a ground-truth value)."""

    def _pct(value: float | None) -> str:
        return "н/д" if value is None else f"{round(value * 100, 1)}%"

    return f"""\
## Order-response: точность по {aggregate["total"]} позициям с ground truth

| Исход | Доля |
|---|---|
| correct_match | {_pct(aggregate["correct_match_rate"])} |
| missing | {_pct(aggregate["missing_rate"])} |
| mismatched | {_pct(aggregate["mismatched_rate"])} |

Price accuracy (точное совпадение, без допуска на округление, только среди \
correct_match): {_pct(aggregate["price_accuracy"])} \
(n={aggregate["price_accuracy_denominator"]})

Quantity accuracy (только среди correct_match): {_pct(aggregate["quantity_accuracy"])} \
(n={aggregate["quantity_accuracy_denominator"]})
"""


def price_ingestion_csv_rows(
    *, document: str, comparisons: list[DualModelComparison]
) -> list[dict]:
    """One row per extracted line — see ADR-0044 §5. manual_label is left
    empty for the user to fill in for rows where needs_manual_review is
    True; agreeing rows don't need it but keep the column for a uniform
    CSV shape."""
    return [
        {
            "document": document,
            "raw_name": comparison.raw_name,
            "needs_manual_review": str(comparison.needs_manual_review),
            "sol_action": comparison.sol_line.decision.action,
            "sol_material_id": str(comparison.sol_line.decision.material_id or ""),
            "luna_action": comparison.luna_line.decision.action,
            "luna_material_id": str(comparison.luna_line.decision.material_id or ""),
            "manual_label": "",
        }
        for comparison in comparisons
    ]


def price_ingestion_markdown_report(
    comparisons: list[DualModelComparison], *, manually_labeled_correct_count: int
) -> str:
    """See ADR-0044 §5: the manual-review rate (= disagreement rate) is
    shown separately from accuracy, and accuracy is explicitly scoped to
    the manually-labeled subset, with the sol/luna-agreement caveat spelled
    out — agreement is not proof of correctness."""
    total = len(comparisons)
    needs_review = [c for c in comparisons if c.needs_manual_review]
    manual_review_rate = (len(needs_review) / total) if total else 0.0

    accuracy = (
        (manually_labeled_correct_count / len(needs_review)) if needs_review else None
    )
    accuracy_str = "н/д" if accuracy is None else f"{round(accuracy * 100, 1)}%"

    return f"""\
## Price-ingestion: двойной заход sol/luna по {total} строкам

Доля строк, потребовавших ручную проверку (= доля расхождений между sol и \
luna): {round(manual_review_rate * 100, 1)}% ({len(needs_review)} из {total})

Точность на размеченной вручную подвыборке расхождений: {accuracy_str} \
(n={len(needs_review)})

**Важно**: согласие между sol и luna не является доказательством правильности \
— обе модели могут совпасть в одной и той же ошибке. Итоговая точность выше \
измерена только на подмножестве расхождений, размеченном вручную, не на \
100% строк документа. См. ADR-0044 §5.
"""
