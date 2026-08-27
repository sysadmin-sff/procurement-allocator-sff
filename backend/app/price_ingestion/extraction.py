"""Step 1 of price-list ingestion: extraction only, no matching — see
ADR-0019 §3. Structurally separate from matching (extraction.py vs
matching.py) because the candidate space for matching is the whole
Material table, unlike ADR-0018's single-call approach where the closed
OrderItem list fits in the same prompt as the document.

ADR-0021: a single call on a whole multi-page PDF is structurally fragile
(observed on a real 14-page/~464-line document — the model sometimes gives
up mid-document with a syntactically valid but incomplete result). PDFs are
split into fixed-size page chunks with 1-page overlap before extraction;
each chunk gets its own call, and results are concatenated in order. This
is invisible to callers — extract_price_list_lines still returns a single
list[ExtractedPriceLine] for the whole document. input_image documents
(single scan/photo) are excluded — already a small single-page input.

ADR-0023: each line also carries page_number — the absolute physical page
of the document it was extracted from (1-indexed). Verified reliable
(15/15 manually checked lines correct on the real reference document,
docs/decisions/0023-price-list-overlap-scoped-dedup.md "Открытые
вопросы") — the prompt tells the model the absolute page range of each
chunk explicitly, rather than relying on it to infer absolute numbering
from a fragment. Used by dedup.py to scope chunk-overlap duplicate
candidates to lines that share the one overlap page between two adjacent
chunks (ADR-0021 §3), instead of comparing every line in the document.

Chunk calls run concurrently (measured: 309s sequential on the real
14-page/~700-line reference document — dominant half of total pipeline
time, see docs/known-issues.md). Same ThreadPoolExecutor + retry/backoff
pattern matching.py already uses for its own network calls (ADR-0022
§2) — chunks are independent (each covers its own page range, no shared
state besides the read-only input file bytes), so parallelizing them is
a direct application of that pattern, not a new design. Results are
concatenated by chunk index (pool.map preserves input order regardless
of completion order), never by thread completion order — a chunk
finishing late must not reorder the document. Unlike matching's
per-line retry isolation, a chunk whose retries are exhausted is NOT
given a placeholder — the whole extraction fails (PriceIngestionError
propagates), same as the pre-parallelization sequential loop already
did on any chunk's first failure. A lost chunk is a lost page range with
no way to signal "some lines are missing" on the review screen (unlike
matching's one-line processing_status="failed"), so silently degrading
to a partial result would hide missing pages instead of surfacing the
failure — worse than today's fail-loud behavior, not an improvement.
"""

from __future__ import annotations

import base64
import io
from concurrent.futures import ThreadPoolExecutor

from openai import APIError, APITimeoutError, OpenAI
from pydantic import BaseModel
from pypdf import PdfReader, PdfWriter

from app.core.config import settings
from app.price_ingestion.retry import RetryExhaustedError, call_with_retry

DEFAULT_PAGES_PER_CHUNK = 3
"""Pages per extraction chunk — ADR-0021 §1. Internal implementation
parameter, not an operational setting like model choice, so a plain
constant rather than an env var."""

EXTRACTION_CONCURRENCY = 6
"""Thread pool size for per-chunk extraction calls. Same value as
matching.py's MATCHING_CONCURRENCY (ADR-0022 §2) — not imported/shared,
since the two are independent internal tuning parameters for two
different call sites that happen to currently agree, not a single
constant with one shared meaning; each can be retuned independently
without implying anything about the other."""


class ExtractedPriceLine(BaseModel):
    raw_name: str
    raw_sku: str | None
    price: float
    currency: str
    availability: int | None
    min_order_qty: int | None
    page_number: int
    """Absolute 1-indexed physical page of the document this line was
    extracted from — ADR-0023. For input_image documents (always a single
    page), always 1. Verified reliable on a real multi-page document
    (15/15 manually checked) — see ADR-0023 "Открытые вопросы"."""


class _ExtractedLineNoPage(BaseModel):
    """Structured-output shape for the input_image path (always a single
    page — no ambiguity to ask the model to resolve, see
    extract_price_list_lines)."""

    raw_name: str
    raw_sku: str | None
    price: float
    currency: str
    availability: int | None
    min_order_qty: int | None


class _ExtractionResultNoPage(BaseModel):
    lines: list[_ExtractedLineNoPage]


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


_PROMPT_NO_PAGE = """\
Ты помогаешь сотруднику отдела закупок извлечь строки из прайс-листа \
поставщика. Прикреплённый документ — прайс-лист (скан/фото, одна страница).

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

_PROMPT_TEMPLATE = """\
Ты помогаешь сотруднику отдела закупок извлечь строки из прайс-листа \
поставщика. Прикреплённый документ — это страницы {start_page}-{end_page} \
(абсолютная нумерация страниц полного документа, начиная с 1) прайс-листа \
(PDF).

Извлеки КАЖДУЮ строку прайса как отдельную позицию. Не пытайся сопоставить \
её ни с чем — только извлечение. Для каждой строки верни:
- raw_name: название материала дословно, как написано в прайсе
- raw_sku: артикул поставщика, если указан; null, если нет
- price: цена за единицу
- currency: валюта (обычно "USD")
- availability: остаток на складе, если указан; null, если нет
- min_order_qty: минимальное количество заказа, если указано; null, если нет
- page_number: номер ФИЗИЧЕСКОЙ страницы документа (абсолютный, в диапазоне \
{start_page}-{end_page}), на которой напечатана эта строка — не относительный \
номер внутри присланного фрагмента, а абсолютный номер страницы полного \
документа.

Если документ нечитаем или не содержит ни одной позиции с ценой — верни \
пустой список lines, не пытайся выдумать позиции.
"""


def _build_file_content(file_bytes: bytes, content_type: str) -> dict:
    file_field = _SUPPORTED_CONTENT_TYPES[content_type]
    encoded = base64.b64encode(file_bytes).decode("ascii")
    data_url = f"data:{content_type};base64,{encoded}"

    if file_field == "input_file":
        return {
            "type": "input_file",
            "filename": "price-list.pdf",
            "file_data": data_url,
        }
    return {"type": "input_image", "image_url": data_url}


def _call_extraction_no_page(client: OpenAI, file_content: dict) -> list[ExtractedPriceLine]:
    """input_image path — single page, no page_number ambiguity to ask the
    model to resolve. Fills page_number=1 on every returned line."""
    try:
        response = client.responses.parse(
            model=settings.openai_price_ingestion_model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": _PROMPT_NO_PAGE},
                        file_content,
                    ],
                }
            ],
            text_format=_ExtractionResultNoPage,
        )
    except (APIError, APITimeoutError) as exc:
        raise PriceIngestionError(
            "Не удалось связаться с сервисом распознавания. Попробуйте ещё раз."
        ) from exc

    parsed = response.output_parsed
    if parsed is None:
        raise PriceIngestionError("Не удалось распознать документ.")

    return [
        ExtractedPriceLine(**line.model_dump(), page_number=1) for line in parsed.lines
    ]


def _call_extraction_raw(
    client: OpenAI, file_content: dict, *, start_page: int, end_page: int
) -> list[ExtractedPriceLine]:
    """The network call itself, with no exception mapping — lets
    RateLimitError (a subclass of APIError) propagate unmodified so
    call_with_retry (ADR-0022 §2) can see and retry it. Wrapping the
    mapped PriceIngestionError instead (as this call's caller used to do
    directly) would hide RateLimitError from the retry helper — it only
    matches openai.RateLimitError specifically, not the broader
    PriceIngestionError. See _call_extraction for the mapped, retried
    version callers should use."""
    prompt = _PROMPT_TEMPLATE.format(start_page=start_page, end_page=end_page)
    response = client.responses.parse(
        model=settings.openai_price_ingestion_model,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    file_content,
                ],
            }
        ],
        text_format=_ExtractionResult,
    )

    parsed = response.output_parsed
    if parsed is None:
        raise PriceIngestionError("Не удалось распознать документ.")

    return parsed.lines


def _call_extraction(
    client: OpenAI, file_content: dict, *, start_page: int, end_page: int
) -> list[ExtractedPriceLine]:
    """One OpenAI call: vision + structured output, extraction only (no
    matching — see module docstring / ADR-0019 §3). start_page/end_page are
    absolute 1-indexed page numbers of the whole document that this chunk
    covers — passed explicitly into the prompt (ADR-0023) so the model
    doesn't have to infer absolute numbering from a fragment. Retries on
    RateLimitError (ADR-0022 §2, same helper matching.py uses) before
    mapping any remaining failure to PriceIngestionError. An empty
    extraction (model found nothing) is not an error and returns an empty
    list normally."""
    try:
        return call_with_retry(
            lambda: _call_extraction_raw(
                client, file_content, start_page=start_page, end_page=end_page
            )
        )
    except RetryExhaustedError as exc:
        raise PriceIngestionError(
            "Не удалось связаться с сервисом распознавания. Попробуйте ещё раз."
        ) from exc
    except (APIError, APITimeoutError) as exc:
        raise PriceIngestionError(
            "Не удалось связаться с сервисом распознавания. Попробуйте ещё раз."
        ) from exc


def _page_chunks(*, total_pages: int, pages_per_chunk: int) -> list[tuple[int, int]]:
    """Splits `total_pages` (0-indexed) into (start, end) inclusive page-index
    ranges of `pages_per_chunk` pages, with a 1-page overlap between adjacent
    chunks — chunk N's last page equals chunk N+1's first page (ADR-0021 §1,
    §3). A document that fits in one chunk yields exactly one range."""
    if total_pages <= pages_per_chunk:
        return [(0, total_pages - 1)]

    chunks: list[tuple[int, int]] = []
    start = 0
    while True:
        end = min(start + pages_per_chunk - 1, total_pages - 1)
        chunks.append((start, end))
        if end >= total_pages - 1:
            break
        start = end
    return chunks


def _extract_pdf_page_range(file_bytes: bytes, start: int, end: int) -> bytes:
    """Returns a new single-PDF byte string containing pages [start, end]
    (inclusive, 0-indexed) of the input PDF."""
    reader = PdfReader(io.BytesIO(file_bytes))
    writer = PdfWriter()
    for page_index in range(start, end + 1):
        writer.add_page(reader.pages[page_index])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _extract_one_chunk(
    client: OpenAI, file_bytes: bytes, content_type: str, *, start: int, end: int, single: bool
) -> list[ExtractedPriceLine]:
    """Runs entirely in the thread pool — builds this chunk's own PDF
    bytes/content payload and makes its own retried network call
    (_call_extraction). No shared mutable state between chunks."""
    chunk_bytes = file_bytes if single else _extract_pdf_page_range(file_bytes, start, end)
    file_content = _build_file_content(chunk_bytes, content_type)
    return _call_extraction(client, file_content, start_page=start + 1, end_page=end + 1)


def extract_price_list_lines(
    *, file_bytes: bytes, content_type: str
) -> list[ExtractedPriceLine]:
    """Extraction step (ADR-0019 §3). For PDFs, internally splits the
    document into page chunks (ADR-0021) and issues one OpenAI call per
    chunk, running the calls concurrently (EXTRACTION_CONCURRENCY, see
    module docstring) and concatenating results in chunk order — never by
    thread completion order — with no deduplication at this stage
    (ADR-0019 §4 dedup, applied after matching, already covers duplicates
    from chunk overlap). For input_image documents (single scan/photo),
    chunking does not apply — one call on the whole document, unchanged
    from before ADR-0021. Raises PriceIngestionError if any chunk's
    retries are exhausted or otherwise fails — a lost chunk has no safe
    partial-result representation (see module docstring), so one failing
    chunk still fails the whole extraction, same as before
    parallelization."""
    if not settings.openai_api_key:
        raise PriceIngestionError(
            "OpenAI API не настроен (отсутствует OPENAI_API_KEY)"
        )

    client = OpenAI(api_key=settings.openai_api_key.get_secret_value())

    if _SUPPORTED_CONTENT_TYPES[content_type] != "input_file":
        file_content = _build_file_content(file_bytes, content_type)
        return _call_extraction_no_page(client, file_content)

    total_pages = len(PdfReader(io.BytesIO(file_bytes)).pages)
    chunks = _page_chunks(total_pages=total_pages, pages_per_chunk=DEFAULT_PAGES_PER_CHUNK)
    single = len(chunks) == 1

    with ThreadPoolExecutor(max_workers=EXTRACTION_CONCURRENCY) as pool:
        # pool.map preserves input order in its return value regardless of
        # which thread finishes first — chunk order in the result is
        # exactly `chunks` order, not completion order.
        chunk_results = list(
            pool.map(
                lambda chunk: _extract_one_chunk(
                    client, file_bytes, content_type,
                    start=chunk[0], end=chunk[1], single=single,
                ),
                chunks,
            )
        )

    all_lines: list[ExtractedPriceLine] = []
    for lines in chunk_results:
        all_lines.extend(lines)

    return all_lines
