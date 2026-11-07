# aicontent-factory

Автономный конвейер генерации и публикации ИИ-контента для пассивного
дохода. ТЗ и план — `docs/PLAN.md`. Решения по развилкам — `docs/DECISIONS.md`.

Статус: инициализация (см. kanban-доску `aicontent-factory`).

## Публичный статус репо и гейт merge (2026-11-07)

- **Репо PUBLIC** (`mytab0r/aicontent-factory`). Причина: branch protection
  с required status checks на GitHub недоступна для private-репо на Free
  (API возвращает 403 «Upgrade to GitHub Pro»), но на **публичных** репо
  — бесплатна. Публичность принята осознанно ради бесплатного гейта.
- **Следствие: бизнес-код и CI-пайплайн видны всем.**
- **Гейт merge**: merge в `master` только с зелёной проверкой `test`.
  Настроен branch protection: required check = `test` (app GitHub Actions),
  strict, `enforce_admins`. Проверено: REST merge без зелёного `test`
  возвращает 405; жёсткий push в master без тестов отклоняется.
- **Аудит секретов (gitleaks)**: вся история сканирована, **0 реальных
  находок** (10 срабатываний `generic-api-key` — ложные positives:
  публичные адреса контрактов USDT/USDC в fixtures/конфиге).