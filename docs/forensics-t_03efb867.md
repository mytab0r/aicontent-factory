# Форензика: удаление контейнера ace-step (инцидент #2, 19.10)

## Верdict
1. Контейнер ace-step ОСТАНОВИЛ workflow oneoff-minimax-spike (ветка exp/minimax-spike, раннер pc,
   карточка t_737ca0ec, run 39184047547): шаг "ACE-Step down" = `docker stop ace-step` в 01:20:36 UTC.
   Это штатный шаг спайка (освобождение VRAM 12GB), с расчётом на авторестарт шагом "ACE-Step up (always)".
2. Контейнер УДАЛИЛ не спайк: в 01:47:11 собственный шаг спайка получил
   «Error response from daemon: No such container: ace-step». Окно удаления: 01:20:39–01:32:04 UTC
   (в 01:32:04 ci-тест уже не резолвил ace-step). Кто-то сделал docker rm остановленного контейнера.
3. Исполнитель rm по логам НЕ ОПРЕДЕЛЯЕТСЯ: docker API call-логов не ведётся, ring docker events
   перезаписан (проверено запросом events 01:15–01:50 19.10 — пусто), Docker Desktop не
   перезапускался (StartTime стабилен 17.10 21:57:25 local, watcher before/after equal).

## Хронология (UTC, все точки — из логов GHA)
- 18.10 09:03 … 19.10 00:33 — ace-step healthy при каждом запуске daily-video (09:03, 09:11, 13:03,
  14:08, 15:24, 17:24, 18:56, 21:18, 00:33). Сбои daily-video 18.10 — НЕ контейнер (quality gate R3/LRA).
- 19.10 01:10:33 — запуск спайка 39184047547; release-guard прошёл (daily-video не активен, час разрешён).
- 19.10 01:20:36 — `docker stop ace-step` (спайк).
- 19.10 01:32:04 — ci 39185677216: «ACE http://ace-step:7865/ недоступен (Name or service not known)».
- 19.10 01:47:11 — спайк, шаг "ACE-Step up": «No such container: ace-step» → run failed.
- 19.10 01:53:29 — xl-probe 39187176052: «No such container: ace-step» (двойное подтверждение).
- 19.10 01:57:13 — карточка t_737ca0ec заблокирована: «ACE-Step container missing on runner host».
- 19.10 01:58+ — все daily-video: «ace-step не healthy за 10 мин» до вечера; восстановлен ~22:57 (smoke green).

## Исключённые подозреваемые (доказательства)
- docker-janitor: janitor.sh «conservative: only forbidden names», BAD_CT
  ^(hya-|comfy|wan|findrec|gpu-check|netprobe|np-|probe-) — ace-step не матчится; скрипт показан целиком
  (forensics v2 run 39342628151). volume/builder prune контейнеры не трогает.
- auto-compact.ps1: compact.log (D:/hermes-codex) 18–19.10 — только «gate skip» (идущие карточки),
  ни одного compact/done; останавливает Docker только на время оптимизации, удалять не умеет.
- disk-guard.ps1: тот же regex-класс целей; в окне не срабатывал.
- xl-probe.yml: единственный workflow с `docker rm -f ace-step`, но rm всегда в паре с rename
  ace-step-new→ace-step и только после healthy нового; в окне 01:20–01:47 не запускался
  (его run 01:50 сам нашёл контейнер пропавшим).
- watchdog.yml: алерт-only (watchdog.py), запуски 10:00/13:39 — вне окна.
- Все GHA-запуски репо в окне 00:20–02:10 (полный список): ci ×3 (rm/rmi только своих pay-* тегов),
  pay-image, oneoff-minimax-spike, daily-video — никто не выполнял docker rm ace-step.
- Docker Desktop/WSL restart: исключён (StartTime стабилен).

## Причинно-следственный вывод
Триггер инцидента — minimax-спайк t_737ca0ec: остановка прод-контейнера на ночь. Само удаление —
внешний `docker rm` (кто именно — недоказуемо ретроспективно: нет audit-log docker API). Уязвимость
класса: остановленный контейнер с restart=unless-stopped выглядит «брошенным» для любого чистильщика
(GHA-раннеров на хосте ~10, у каждого полный доступ к сокету), и удалить его можно без следа.

## Митигация (рекомендации)
1. Спайку запретить docker stop прод-контейнера: отдельный свободный GPU-слот либо приглашение
   «спайк только 10–16 UTC» (уже частично есть Release guard — расширить).
2. Метка защиты + контроль: `docker update --label-add protected=ace ace-step`; в janitor.sh добавить
   правило: контейнер с label protected=ace и статусом exited > 30 мин → `docker start` (самолечение)
   + TG-алерт. Это закрывает класс «остановил и забыли/удалили».
3. Аудит на будущее: включить access-log на auth-proxy (2376) и/или ace-proxy (tecnativa) — тогда
   следующий инцидент будет с именем виновника за минуты.


## Дополнение 20.10 (форензика v4, run 39345960179)

**auth-proxy (nginx 2376) проверен по access-логу**: окно 19.10 01:00–03:00 UTC — 500 запросов, НОЛЬ вызовов DELETE / stop / rm / prune (в т.ч. ноль обращений к /containers/ace-step кроме GET /events). Значит rm выполнен МИМО auth-proxy — через локальный docker.sock (GHA-раннер или локальный процесс). Прямая атрибуция исполнителя rm исчерпана: все доступные журналы (events ring, auth-proxy, watcher Docker Desktop, логи всех GHA-ранов окна) проверены.

**Текущее состояние**: `docker inspect ace-step` → `state=running health=healthy image=ghcr.io/ace-step/ace-step-1.5:latest` (20.10 00:26 UTC). Smoke-release-runner 39332775321: `status=completed conclusion=success` (gh api, 20.10).

**Блокировка повторения (механизмы)**:
1. Merged в master PR #110 (57d3eda, CI 3/3): daily-video "ACE-Step up" пересоздаёт контейнер при отсутствии, health-окно 18 мин — rm перестаёт ломать пайплайн.
2. H-051 → Codex (хост): janitor (каждую минуту, через auth-proxy) получает recreate-if-missing + запрет stop/rm/prune ace-step — сокращает окно простоя до ≤1 мин и исключает janitor как исполнителя rm навсегда.
3. Рекомендация вне скоупа: access-log локального docker.sock (systemd/journald docker.socket) — следующий инцидент даст имя виновника.


## Дополнение v5 (20.10, ревью run287): исполнитель НАЙДЕН — D:\hermes-runner\disk-guard.ps1

Источник: хост-скрипт `D:\hermes-runner\disk-guard.ps1` (сервис runner-disk-guard в C:\Users\magic\tools\admin\services.json, every 900 с, enabled=true). Вызывает docker CLI на хосте напрямую (мимо auth-proxy — поэтому в access-логе 2376 ноль DELETE). Пороги: `$limitGB = 60; $minFreeGB = 40`; vhdx=144.9 ГБ, freeD=31.1 ГБ ⇒ условие истинно на КАЖДОМ тике (657 «aggressive image prune» с 09.10).

Старый код (бэкап D:\hermes-runner\disk-guard.ps1.bak-t03efb867):
```
docker container prune -f --filter until=24h     # удаляет ЛЮБОЙ остановленный контейнер старше 24ч
docker image prune -f
docker image prune -a -f --filter until=72h      # удаляет любой образ без контейнера, старше 72ч
```
Лог D:\hermes-runner\disk-guard.log пишет ЛОКАЛЬНОЕ время ПК (UTC+3: хвост лога 20.10 05:15 при date -u 02:15). Тики вокруг инцидента:
```
2026-10-19T04:14:40 over limit: prune ... 04:14:43 aggressive image prune done   (= 01:14 UTC, ace-step ещё running)
2026-10-19T04:29:41 over limit: prune ... 04:29:48 aggressive image prune done   (= 01:29 UTC, через 9 мин после docker stop спайком)
```
Механика: 01:20:36 UTC спайк остановил ace-step (создан 13.10, старше 24ч) → тик 01:29:41 UTC (04:29:41 local): `container prune --filter until=24h` удалил остановленный ace-step → тот же тик `image prune -a --filter until=72h` удалил ставший неиспользуемым образ ghcr.io/ace-step/ace-step-1.5:latest (создан 2026-05-18, 20.7 ГБ). Совпадает с окном 01:20:39–01:32:04 и с пропажей контейнера И образа одновременно.

Проверка остальных rmi/prune (цитаты):
- build-ace-step-image.yml, шаг «prune garbage»: `docker image prune -f && docker builder prune -f --filter until=168h` — только dangling, тегированный образ не трогает; последний запуск 18.10 09:29 (39115507233, login failure) — вне окна.
- docker-janitor (janitor.sh): `docker volume prune -f`, `docker builder prune -f --filter until=24h`, rm только по BAD_CT — образы/ace-step не трогает.
- C:\dockerlocal\disk-guard.ps1 и hermes-ops\disk-guard.ps1: `docker builder prune -af`, rm по BAD_CT — образы не трогают; guard.log пуст в окне.
- ci.yml: `docker rmi -f pay-e2e:$GITHUB_RUN_ID` — только свой тег.
- ensure_ace_step.sh: rmi только лишних копий repo ace-step, не используемых контейнером.

## Установленные механизмы (проверено выводом)
1. disk-guard.ps1 заменён (источник в репо: deploy/gpu-pc/host/disk-guard.ps1, установка run 39356945427 success; первый тик новой версии 20.10 05:14:59 local отработал до конца, ws=0GB — скрипт исполняется (run 39358951590)):
   - `container prune` только когда ace-step running, иначе лог «SKIP container prune: ace-step not running»;
   - `image prune -a` только когда контейнер ace-step существует (prune -a не удаляет образ, используемый контейнером), иначе «SKIP aggressive image prune».
2. janitor.sh H-051 установлен (C:\Users\magic\hermes-ops\janitor\janitor.sh, 20.10 00:41, бэкап .bak-h051): guard_ace — recreate при пропаже, start если остановлен >10 мин, ace-step исключён из rm.
3. Аудит docker.sock: контейнер docker-audit (restart unless-stopped) пишет `docker events` type=container|image в D:\hermes-runner\docker-events.jsonl (ротация 50 МБ). Проверено: тестовый контейнер audit-probe попал в лог (create/attach/start); через 23 мин 1309 событий, docker-audit Up (run 39358951590).
4. PR #110 (daily-video recreate) — остаётся вторым эшелоном.
