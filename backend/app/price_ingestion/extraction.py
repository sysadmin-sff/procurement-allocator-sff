"""Step 1 of price-list ingestion: extraction only, no matching — see
ADR-0019 §3. Structurally separate from matching (extraction.py vs
matching.py) because the candidate space for matching is the whole
Material table, unlike ADR-0018's single-call approach where the closed
OrderItem list fits in the same prompt as the document.
"""

from __future__ import annotations

import base64

from openai import APIError, APITimeoutError, OpenAI
from pydantic import BaseModel

from app.core.config import settings


class ExtractedPriceLine(BaseModel):
    raw_name: str
    raw_sku: str | None
    price: float
    currency: str
    availability: int | None
    min_order_qty: int | None


class _ExtractionResult(BaseModel):
    lines: list[ExtractedPriceLine]


class PriceIngestionError(Exception):
    """OpenAI API unreachable, timed out, or returned an error — mirrors
    OrderResponseParsingError (ADR-0018 §6)."""


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


_PROMPT = """\
Ты помогаешь сотруднику отдела закупок извлечь строки из прайс-листа \
поставщика. Прикреплённый документ — прайс-лист (PDF или скан/фото).

Извлеки КАЖДУЮ строку прайса как отдельную позицию. Не пытайся сопоставить \
её ни с чем — только извлечение. Для каждой строки верни:
- raw_name: название материала дословно, как написано в прайсе
- raw_sku: артикул поставщика, если указан; null, если нет
- price: цена за единицу
- currency: валюта (обычно "USD")
- availability: остаток на складе, если указан; null, если нет
- min_order_qty: минимальное количество заказа, если указано; null, если нет

Если документ нечитаем или не содержит ни одной позиции с ценой — верни \
пустой список lines, не пытайся выдумать позиции.
"""


def extract_price_list_lines(
    *, file_bytes: bytes, content_type: str
) -> list[ExtractedPriceLine]:
    """One OpenAI call: vision + structured output, extraction only (no
    matching — see module docstring / ADR-0019 §3). Raises
    PriceIngestionError on any API failure. An empty extraction (model
    found nothing) is not an error and returns an empty list normally."""
    if not settings.openai_api_key:
        raise PriceIngestionError(
            "OpenAI API не настроен (отсутствует OPENAI_API_KEY)"
        )

    client = OpenAI(api_key=settings.openai_api_key)

    file_field = _SUPPORTED_CONTENT_TYPES[content_type]
    encoded = base64.b64encode(file_bytes).decode("ascii")
    data_url = f"data:{content_type};base64,{encoded}"

    if file_field == "input_file":
        file_content = {
            "type": "input_file",
            "filename": "price-list.pdf",
            "file_data": data_url,
        }
    else:
        file_content = {"type": "input_image", "image_url": data_url}

    try:
        response = client.responses.parse(
            model=settings.openai_price_ingestion_model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": _PROMPT},
                        file_content,
                    ],
                }
            ],
            text_format=_ExtractionResult,
        )
    except (APIError, APITimeoutError) as exc:
        raise PriceIngestionError(
            "Не удалось связаться с сервисом распознавания. Попробуйте ещё раз."
        ) from exc

    parsed = response.output_parsed
    if parsed is None:
        raise PriceIngestionError("Не удалось распознать документ.")

    return parsed.lines
