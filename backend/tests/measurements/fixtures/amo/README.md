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

**Не из реальных ответов.** В `probe_out` нет ответов `/leads`, `/leads/pipelines` и
`/users`. `leads.json`, `pipelines.json` и `users.json` написаны по документации API
v4 и по полям, которые читают пробные скрипты. Сверить со счётчиками dry-run
(ADR-0051, критерий 12).
