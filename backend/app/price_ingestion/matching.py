"""Step 2 of price-list ingestion: matching, one call per line — see
ADR-0019 §2-4. Exact-alias short-circuit skips embedding + LLM entirely;
otherwise pgvector top-K + LLM decision. After all lines are matched,
new-line embeddings (already computed for candidate search — reused, not
recomputed) are pairwise-compared to flag possible duplicates within the
same import (ADR-0019 §4).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal

from openai import APIError, APITimeoutError, OpenAI
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Material
from app.price_ingestion.candidates import (
    DUPLICATE_DISTANCE_THRESHOLD,
    find_known_alias,
    find_top_candidates,
)
from app.price_ingestion.embeddings import embed_text, material_embedding_input
from app.price_ingestion.extraction import ExtractedPriceLine, PriceIngestionError


class MatchDecision(BaseModel):
    action: Literal["match", "new"]
    material_id: uuid.UUID | None
    confidence: float
    reasoning: str
    suggested_internal_sku: str | None


@dataclass
class MatchedLine:
    extracted: ExtractedPriceLine
    decision: MatchDecision
    embedding: list[float]
    possible_duplicate_of: list[int] = field(default_factory=list)


def _candidate_context(candidates: list[Material]) -> str:
    lines = [
        f"- id={m.id}, название={m.canonical_name!r}, категория={m.category!r}, "
        f"единица={m.unit!r}, атрибуты={m.attributes!r}"
        for m in candidates
    ]
    return "\n".join(lines) if lines else "(нет кандидатов)"


_PROMPT_TEMPLATE = """\
Ты помогаешь сотруднику отдела закупок сопоставить строку прайс-листа \
поставщика с уже известной базой материалов.

Строка прайса: название={raw_name!r}, артикул поставщика={raw_sku!r}.

Похожие материалы из нашей базы (топ-5 по векторному сходству):
{candidates_context}

Реши: это уже известный нам материал (один из списка выше) или новый, \
которого ещё нет в базе?

Верни:
- action: "match", если это один из материалов выше; "new", если это \
новый материал, которого нет в списке
- material_id: id материала из списка выше, если action="match"; null, \
если action="new"
- confidence: число от 0 до 1 — насколько ты уверен в решении
- reasoning: кратко, почему принято такое решение
- suggested_internal_sku: если action="new", предложи черновой internal_sku \
(короткий, по образцу существующих в базе, например на основе категории/ \
названия); null, если action="match"
"""


def _decide_match(
    raw_name: str, raw_sku: str | None, candidates: list[Material]
) -> MatchDecision:
    if not settings.openai_api_key:
        raise PriceIngestionError(
            "OpenAI API не настроен (отсутствует OPENAI_API_KEY)"
        )

    client = OpenAI(api_key=settings.openai_api_key)
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


def _cosine_distance(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 1.0
    return 1.0 - dot / (norm_a * norm_b)


def _flag_duplicate_new_lines(results: list[MatchedLine]) -> None:
    """Pairwise cosine distance between all action="new" lines in this
    batch, reusing embeddings already computed during matching — see
    ADR-0019 §4. Mutates possible_duplicate_of on the affected results."""
    new_indices = [i for i, r in enumerate(results) if r.decision.action == "new"]
    for i in new_indices:
        for j in new_indices:
            if i == j:
                continue
            distance = _cosine_distance(results[i].embedding, results[j].embedding)
            if distance < DUPLICATE_DISTANCE_THRESHOLD:
                results[i].possible_duplicate_of.append(j)


def match_price_list_lines(
    db: Session, supplier_id: uuid.UUID, lines: list[ExtractedPriceLine]
) -> list[MatchedLine]:
    """Matches each extracted line — alias short-circuit first (ADR-0019
    §2), otherwise vector search + LLM (ADR-0019 §3) — then flags
    possible duplicate action="new" lines within this batch (ADR-0019 §4).
    """
    results: list[MatchedLine] = []

    for line in lines:
        known_alias = find_known_alias(db, supplier_id, line.raw_name)
        if known_alias is not None:
            decision = MatchDecision(
                action="match",
                material_id=known_alias.material_id,
                confidence=1.0,
                reasoning="known alias",
                suggested_internal_sku=None,
            )
            # Эмбеддинг не нужен для known-alias пути (ADR-0019 §2), но
            # possible_duplicate_of применяется только к action="new" —
            # пустой вектор здесь никогда не используется в сравнении.
            results.append(MatchedLine(extracted=line, decision=decision, embedding=[]))
            continue

        embedding = embed_text(material_embedding_input(line.raw_name, {}))
        candidates = find_top_candidates(db, embedding)
        decision = _decide_match(line.raw_name, line.raw_sku, candidates)
        results.append(MatchedLine(extracted=line, decision=decision, embedding=embedding))

    _flag_duplicate_new_lines(results)
    return results
