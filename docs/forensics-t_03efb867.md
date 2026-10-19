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
