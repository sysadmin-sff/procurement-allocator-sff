"""Step 2 of price-list ingestion: matching — see ADR-0019 §2-4, extended
by ADR-0022 for chunk-overlap volume and throughput, ADR-0023 for
correctness of the early-dedup mechanism, and ADR-0025 for matching
against a fixed, small catalog instead of an open, growing one:

- Fixed-catalog matching (ADR-0025 §1). The catalog is closed by
  construction now (~300 materials, only extended manually via
  /materials, never by this pipeline) and small enough to pass whole —
  vector top-K prefiltering (find_top_candidates/embed_text on raw price
  lines) existed only to work around the context-size limit of an open,
  growing catalog (ADR-0019 §3); that limit no longer applies, so the
  mechanism is removed from this path entirely. _decide_match now takes
  the full material list. find_known_alias (ADR-0019 §2) is unaffected —
  it is checked first regardless of what the expensive path looks like.
- Early dedup (ADR-0022 §1, rewritten by ADR-0023) — see EARLY_DEDUP_ENABLED
  below. Lines are grouped by page_number (ADR-0021 §3 overlap page) +
  exact raw_name match (after whitespace/case normalization) —
  app.price_ingestion.dedup.group_duplicate_lines. Only the representative
  of each group takes the expensive alias/LLM path; the rest inherit its
  decision, flagged via possible_duplicate_of. No line is excluded from
  the batch.
- Concurrency (ADR-0022 §2) — still enabled, independent of the above:
  alias short-circuit (touches `db`, not thread-safe — see
  app.core.database) runs sequentially in the main thread for every line
  first. Only the network-only call (_decide_match) runs in a
  ThreadPoolExecutor, with retry/backoff on RateLimitError
  (app.price_ingestion.retry). A line whose retries are exhausted is
  marked processing_status="failed" instead of failing the whole batch.

After all lines are matched, action="match" duplicates (same material_id
decided independently for two lines) are flagged by exact id equality —
ADR-0021 §3, a direct consequence of that ADR's page-overlap chunking. The
action="new" duplicate branch (pairwise embedding distance) no longer has
any input to act on — action="new" was removed by ADR-0025 §3 — and is
removed together with it.
"""

from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Literal

from openai import APIError, APITimeoutError, OpenAI
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Material
from app.price_ingestion.candidates import find_known_alias
from app.price_ingestion.dedup import group_duplicate_lines
from app.price_ingestion.extraction import ExtractedPriceLine, PriceIngestionError
from app.price_ingestion.retry import RetryExhaustedError, call_with_retry

logger = logging.getLogger(__name__)

MATCHING_CONCURRENCY = 6
"""Thread pool size for _decide_match — ADR-0022 §2. Internal
implementation parameter, not an env var (same class of decision as
DEFAULT_PAGES_PER_CHUNK in extraction.py)."""

NOT_FOUND_LOG_CONFIDENCE_THRESHOLD = 0.5
"""ADR-0025 §5 final addition: not_found decisions at or above this
confidence are logged (structured log call, not persisted — see
module docstring) so the review-trigger condition in ADR-0025 §5 has an
actual data source instead of relying on an employee noticing a missing
line they cannot see by construction of this same decision."""

EARLY_DEDUP_ENABLED = True
"""Re-enabled by ADR-0023 after the ADR-0022 §1 grouping mechanism was
fixed — see the module docstring above and
docs/decisions/0023-price-list-overlap-scoped-dedup.md. Candidates are now
scoped to same-page (chunk-overlap) pairs and use exact raw_name match
only, not a whole-document embedding-distance comparison. Confirmed on the
real reference document (14 pages, 706 lines): candidate space fell from
245,350 (whole document, ADR-0022 baseline) to 8,945 (overlap-page pairs),
of which 158 are exact-match duplicates — every one manually spot-checked
was a genuine same-position duplicate, none were unrelated products. See
ADR-0023 for why a secondary distance threshold was investigated and
rejected (no separating gap between real duplicates and distinct
product-line variants, even within the overlap-page-scoped set)."""

_INHERITED_REASONING_NOTE = (
    " (унаследовано от строки-представителя этого импорта, не пересчитано)"
)


class MatchDecision(BaseModel):
    action: Literal["match", "not_found"]
    material_id: uuid.UUID | None
    confidence: float
    reasoning: str


@dataclass
class MatchedLine:
    extracted: ExtractedPriceLine
    decision: MatchDecision
    possible_duplicate_of: list[int] = field(default_factory=list)
    processing_status: str | None = None
    """None = processed normally. "failed" = retry exhausted for this
    line's LLM call — see ADR-0022 §2."""


def _candidate_context(candidates: list[Material]) -> str:
    lines = [
        f"- id={m.id}, sku={m.internal_sku!r}, название={m.canonical_name!r}, "
        f"категория={m.category!r}, единица={m.unit!r}"
        for m in candidates
    ]
    return "\n".join(lines) if lines else "(каталог пуст)"


_PROMPT_TEMPLATE = """\
Ты помогаешь сотруднику отдела закупок сопоставить строку прайс-листа \
поставщика с уже известной базой материалов. База материалов закрыта — \
ты не создаёшь новые материалы, только ищешь совпадение среди уже \
существующих.

Строка прайса: название={raw_name!r}, артикул поставщика={raw_sku!r}.

Вся база материалов:
{candidates_context}

Реши: это один из материалов базы выше, или совпадения в базе нет?

Верни:
- action: "match", если это один из материалов выше; "not_found", если \
совпадения в списке нет
- material_id: id материала из списка выше, если action="match"; null, \
если action="not_found"
- confidence: число от 0 до 1 — насколько ты уверен в решении
- reasoning: кратко, почему принято такое решение
"""


def _decide_match(
    raw_name: str, raw_sku: str | None, candidates: list[Material]
) -> MatchDecision:
    if not settings.openai_api_key:
        raise PriceIngestionError(
            "OpenAI API не настроен (отсутствует OPENAI_API_KEY)"
        )

    client = OpenAI(api_key=settings.openai_api_key.get_secret_value())
    prompt = _PROMPT_TEMPLATE.format(
        raw_name=raw_name,
        raw_sku=raw_sku,
        candidates_context=_candidate_context(candidates),
    )

    try:
        response = client.responses.parse(
            model=settings.openai_price_ingestion_model,
            input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            text_format=MatchDecision,
        )
    except (APIError, APITimeoutError) as exc:
        raise PriceIngestionError(
            "Не удалось связаться с сервисом сопоставления. Попробуйте ещё раз."
        ) from exc

    parsed = response.output_parsed
    if parsed is None:
        raise PriceIngestionError("Не удалось сопоставить строку прайса.")
    return parsed


def _log_low_confidence_not_found(raw_name: str, decision: MatchDecision) -> None:
    """ADR-0025 §5 final addition — structured log (not persisted, not
    shown on any screen) for action="not_found" decisions the model
    wasn't confident about, so the review-trigger condition in ADR-0025 §5
    ("do real matches get silently dropped?") has an actual data source.
    Same style as the embedding-failure graceful degradation (ADR-0019
    §1): a plain log call at the point of the decision, no new table."""
    if decision.action != "not_found" or decision.confidence < NOT_FOUND_LOG_CONFIDENCE_THRESHOLD:
        return
    logger.info(
        "price_ingestion not_found decision near threshold: raw_name=%r confidence=%s reasoning=%r",
        raw_name,
        decision.confidence,
        decision.reasoning,
    )


def _flag_duplicate_lines(results: list[MatchedLine]) -> None:
    """Flags possible duplicates within this batch — ADR-0019 §4, extended
    by ADR-0021 §3 to also cover action="match" pairs (page-overlap
    chunking, ADR-0021, can make two chunks each independently decide
    action="match" on the same material_id).

    action="match": exact material_id equality — no distance measure
    needed, the id either matches or it doesn't. The former action="new"
    branch (pairwise embedding-distance comparison) had no input left
    once ADR-0025 §3 removed that action, and is removed with it.

    Mutates possible_duplicate_of on the affected results. Idempotent
    against pairs already flagged earlier in the pipeline (ADR-0022 §1
    early dedup already sets possible_duplicate_of on chunk-overlap
    followers before this runs) — never appends an index already present."""
    match_indices = [i for i, r in enumerate(results) if r.decision.action == "match"]
    for i in match_indices:
        for j in match_indices:
            if i == j or j in results[i].possible_duplicate_of:
                continue
            if results[i].decision.material_id == results[j].decision.material_id:
                results[i].possible_duplicate_of.append(j)


def _downgrade_hallucinated_match(
    decision: MatchDecision, candidates: list[Material]
) -> MatchDecision:
    """The LLM hallucinated a material_id that was never among the
    candidates shown to it in this call. Trusting it as-is would write a
    dangling FK and fail the whole batch's db.commit() — downgrade to
    "not_found" so only this one line needs re-review instead of losing
    the entire import (ADR-0019: nothing is trusted blindly, human reviews
    everything). "not_found" (not "new" — removed by ADR-0025 §3) since
    this pipeline no longer proposes new materials at all."""
    if decision.action != "match" or decision.material_id in {c.id for c in candidates}:
        return decision
    return MatchDecision(
        action="not_found",
        material_id=None,
        confidence=min(decision.confidence, 0.3),
        reasoning=(
            f"LLM proposed material_id not among candidates shown ({decision.reasoning})"
        ),
    )


@dataclass
class _PendingLine:
    """A line that needs its own expensive matching call — not covered by
    the alias short-circuit or early dedup (ADR-0022 §1/§2)."""

    index: int
    line: ExtractedPriceLine


def _resolve_pending_line(pending: _PendingLine, catalog: list[Material]) -> MatchedLine:
    """Runs entirely in the thread pool — _decide_match is the only
    network call here, wrapped in retry/backoff (ADR-0022 §2). A line
    whose retries are exhausted is marked processing_status="failed"
    instead of raising, so one line's rate-limit exhaustion never fails
    the whole batch. `catalog` is the full material list (ADR-0025 §1),
    fixed for the whole import, not looked up per line."""
    try:
        decision = call_with_retry(
            lambda: _decide_match(pending.line.raw_name, pending.line.raw_sku, catalog)
        )
    except RetryExhaustedError:
        failed_decision = MatchDecision(
            action="not_found",
            material_id=None,
            confidence=0.0,
            reasoning="",
        )
        return MatchedLine(
            extracted=pending.line,
            decision=failed_decision,
            processing_status="failed",
        )

    decision = _downgrade_hallucinated_match(decision, catalog)
    _log_low_confidence_not_found(pending.line.raw_name, decision)
    return MatchedLine(extracted=pending.line, decision=decision)


def match_price_list_lines(
    db: Session, supplier_id: uuid.UUID, lines: list[ExtractedPriceLine]
) -> list[MatchedLine]:
    """Matches each extracted line — see ADR-0019 §2/§4, ADR-0022 §1-2, and
    ADR-0025 §1-3:

    1. If EARLY_DEDUP_ENABLED, group lines by page_number + exact raw_name
       match (ADR-0022 §1/ADR-0023) — only the first line of each group
       ("representative") takes the expensive path below; the rest
       inherit its decision.
    2. Load the full Material catalog once for the whole import (ADR-0025
       §1 — no per-line vector search, no per-line DB query for
       candidates).
    3. For each representative: alias short-circuit (ADR-0019 §2,
       sequential in the main thread — db is not thread-safe, ADR-0022
       §2), else queued for an LLM decision against the full catalog.
    4. Lines still needing an LLM decision run through the pool
       (concurrency MATCHING_CONCURRENCY), each wrapped in retry/backoff;
       exhausted retries mark that one line processing_status="failed"
       without affecting the rest.
    5. Followers (only possible when EARLY_DEDUP_ENABLED) inherit their
       representative's decision, get possible_duplicate_of pointing at
       it, and never make their own network call.
    6. Post-match duplicate flagging (ADR-0019 §4 / ADR-0021 §3) runs on
       the assembled results, same as before ADR-0022.
    """
    if not lines:
        return []

    catalog = list(db.scalars(select(Material)).all())

    representative_of = (
        group_duplicate_lines(
            raw_names=[line.raw_name for line in lines],
            page_numbers=[line.page_number for line in lines],
        )
        if EARLY_DEDUP_ENABLED
        else list(range(len(lines)))
    )

    # Sequential, main-thread, db-touching pass over every representative
    # (or non-duplicated) line — alias short-circuit only. Followers
    # (representative_of[i] != i) do nothing here.
    resolved: dict[int, MatchedLine] = {}
    pending: list[_PendingLine] = []
    for i, line in enumerate(lines):
        if representative_of[i] != i:
            continue

        known_alias = find_known_alias(db, supplier_id, line.raw_name)
        if known_alias is not None:
            decision = MatchDecision(
                action="match",
                material_id=known_alias.material_id,
                confidence=1.0,
                reasoning="known alias",
            )
            resolved[i] = MatchedLine(extracted=line, decision=decision)
            continue

        pending.append(_PendingLine(index=i, line=line))

    if pending:
        with ThreadPoolExecutor(max_workers=MATCHING_CONCURRENCY) as pool:
            resolved_pending = list(
                pool.map(lambda p: _resolve_pending_line(p, catalog), pending)
            )
        for p, matched_line in zip(pending, resolved_pending, strict=True):
            resolved[p.index] = matched_line

    results: list[MatchedLine] = []
    for i, line in enumerate(lines):
        rep = representative_of[i]
        if rep == i:
            results.append(resolved[i])
            continue

        representative = resolved[rep]
        inherited_decision = MatchDecision(
            action=representative.decision.action,
            material_id=representative.decision.material_id,
            confidence=representative.decision.confidence,
            reasoning=representative.decision.reasoning + _INHERITED_REASONING_NOTE,
        )
        results.append(
            MatchedLine(
                extracted=line,
                decision=inherited_decision,
                possible_duplicate_of=[rep],
                processing_status=representative.processing_status,
            )
        )

    _flag_duplicate_lines(results)
    return results
