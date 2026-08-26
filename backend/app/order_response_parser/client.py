"""OpenAI client wrapper for supplier order-response parsing — see ADR-0018 §1-2.

One call, vision + structured outputs: extraction and matching happen in the
same pass against the closed list of this Order's OrderItem (ADR-0018 §2 —
unlike price-list ingestion, docs/spec.md §3, the candidate space here is
small enough to fit in the prompt whole, so there is no separate
vector-search/matching step). This module only talks to OpenAI; grouping the
result into matched/missing/extra (ADR-0018 §3) lives in service.py.
"""

from __future__ import annotations

import base64
import uuid

from openai import APIError, APITimeoutError, OpenAI
from pydantic import BaseModel

from app.core.config import settings


class ExtractedLine(BaseModel):
    raw_description: str
    matched_order_item_id: uuid.UUID | None
    price: float
    quantity: int | None
    confidence: str
    reasoning: str


class ExtractionResult(BaseModel):
    lines: list[ExtractedLine]


class OrderResponseParsingError(Exception):
    """OpenAI API unreachable, timed out, or returned an error — see
    ADR-0018 п.6. Carries a human-readable message so the API layer can
    surface "не удалось распознать документ" instead of a bare 500."""


_SUPPORTED_CONTENT_TYPES = {
    "application/pdf": "input_file",
    "image/png": "input_image",
    "image/jpeg": "input_image",
    "image/webp": "input_image",
}


class UnsupportedFileTypeError(Exception):
    def __init__(self, content_type: str | None):
        self.content_type = content_type
        super().__init__(f"Unsupported file content type: {content_type}")


def validate_content_type(content_type: str | None) -> None:
    if content_type not in _SUPPORTED_CONTENT_TYPES:
        raise UnsupportedFileTypeError(content_type)


_PROMPT_TEMPLATE = """\
Ты помогаешь сотруднику отдела закупок сопоставить ответ поставщика на \
заказ с уже известным списком позиций заказа.

Ниже — список позиций заказа (наш план, "OrderItem"), которые мы отправили \
поставщику. Каждая позиция имеет id, название материала, количество и цену, \
которую мы рассчитали и отправили:

{order_items_context}

Прикреплённый документ — ответ поставщика (PDF или фото счёта/переписки). \
Извлеки из него КАЖДУЮ позицию с ценой и, если возможно, сопостави её с \
одной из позиций заказа выше по смыслу (названия могут сильно отличаться \
текстуально, но описывать один и тот же материал — используй оба контекста: \
что написано в документе и что мы заказывали).

Для каждой найденной в документе строки верни:
- raw_description: как написано в документе поставщика, дословно
- matched_order_item_id: id позиции заказа выше, если эта строка явно \
соответствует одной из них; null, если строка не соответствует ни одной \
позиции заказа (внеплановая позиция, либо описание слишком отличается, \
чтобы быть уверенным)
- price: цена за единицу, как указано в документе
- quantity: количество, если указано в документе; null, если не указано
- confidence: "high" | "medium" | "low" — насколько ты уверен в сопоставлении \
(для matched_order_item_id = null тоже укажи уверенность в том, что это \
действительно новая позиция, а не пропущенное сопоставление)
- reasoning: кратко, почему сопоставлено именно так (или почему не \
сопоставлено ни с чем)

Если документ нечитаем или не содержит ни одной позиции с ценой — верни \
пустой список lines, не пытайся выдумать позиции.
"""


def _order_items_context(order_items: list[dict]) -> str:
    lines = [
        f"- id={item['id']}, материал={item['canonical_name']!r}, "
        f"кол-во={item['quantity']}, наша цена={item['quoted_price']}"
        for item in order_items
    ]
    return "\n".join(lines)


def parse_order_response_document(
    *,
    file_bytes: bytes,
    content_type: str,
    order_items: list[dict],
) -> list[ExtractedLine]:
    """One OpenAI call: vision + structured output. order_items is a list of
    dicts with keys id/canonical_name/quantity/quoted_price for this Order's
    OrderItem — the closed candidate set for matching (ADR-0018 §2).

    Raises OrderResponseParsingError on any API failure (network, timeout,
    API-side error) — never lets the raw OpenAI exception surface past this
    module. An empty extraction (model found nothing) is not an error and
    returns an empty list normally — see ADR-0018 п.6.
    """
    if not settings.openai_api_key:
        raise OrderResponseParsingError(
            "OpenAI API не настроен (отсутствует OPENAI_API_KEY) — введите цены вручную."
        )

    client = OpenAI(api_key=settings.openai_api_key.get_secret_value())
    prompt = _PROMPT_TEMPLATE.format(order_items_context=_order_items_context(order_items))

    file_field = _SUPPORTED_CONTENT_TYPES[content_type]
    encoded = base64.b64encode(file_bytes).decode("ascii")
    data_url = f"data:{content_type};base64,{encoded}"

    if file_field == "input_file":
        file_content = {
            "type": "input_file",
            "filename": "order-response.pdf",
            "file_data": data_url,
        }
    else:
        file_content = {"type": "input_image", "image_url": data_url}

    try:
        response = client.responses.parse(
            model=settings.openai_order_response_model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        file_content,
                    ],
                }
            ],
            text_format=ExtractionResult,
        )
    except (APIError, APITimeoutError) as exc:
        raise OrderResponseParsingError(
            "Не удалось связаться с сервисом распознавания. Попробуйте ещё раз "
            "или введите цены вручную построчно."
        ) from exc

    parsed = response.output_parsed
    if parsed is None:
        raise OrderResponseParsingError(
            "Не удалось распознать документ. Проверьте качество файла или "
            "введите цены вручную построчно."
        )

    return parsed.lines
