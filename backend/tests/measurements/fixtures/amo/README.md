# Фикстуры ответов amoCRM (ADR-0051)

Обезличены: `text`, `result.text`, имена, названия сделок, email и хост аккаунта
заменены синтетикой. id, типы, вложенность, форматы времени и пустые значения
(`[]` у `value_after`, `result: []` или объект) сохранены как в ответах amo.

| Фикстура | Источник структуры (`scripts/probe_out/`, не в git) |
|---|---|
| `tasks_page.json` | `adr2_tasks_variant_4.json` |
| `task_with_result.json` | `adr2_task_18313159.json` |
| `task_empty_result.json` | `adr2_task_18313193.json` |
| `events_field_784029.json` | `adr2_field_a.json` |
| `events_lead_status_changed.json` | `adr_events_lead_status_changed.json` |
| `events_task_deadline_changed.json` | `adr_events_task_deadline_changed.json` |
| `events_task_deleted.json` | `adr_events_task_deleted.json` |
| `events_task_type_changed.json` | `adr_events_task_type_changed.json` |
| `events_task_completed.json` | `adr2_task_events.json` |
| `custom_fields.json` | `adr_field.json` (элемент), конверт как в `amo_adr_probe.py` |
| `leads.json` | `adr4_leads_200.json` (пачка из трёх `filter[id][]`) |
| `pipelines.json` | `adr4_pipelines_200.json` |
| `users.json` | `adr4_users_200.json`, оставлены два аккаунта замерщиков |

**Одно исключение.** Ни у одной из трёх сделок пробы поле Site Visit Result
(`784029`) в снимке не заполнено. Его запись в первой сделке `leads.json` собрана по
структуре реального select-поля из того же ответа (те же ключи и вложенность
`values[].value/enum_id/enum_code`, `is_masked`). Значения прочих полей, названия
сделок, полей, тегов, воронок и статусов заменены синтетикой. Статусы сделок,
воронки, `is_active` и `is_archive` сохранены как в ответах.
