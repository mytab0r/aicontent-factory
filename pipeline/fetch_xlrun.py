#!/usr/bin/env python3
"""t_b4006a6e: слепая отправка A/B сэмплов владельцу через TG sendAudio + salvage.

Зачем: Artifact storage quota GitHub исчерпана (пересчёт 6-12 ч), артефакт
gate-samples не грузится. /tmp/xlrun на контейнере раннера pc переживает
прогоны — результаты прошлого прогона спасаем и отдаём в TG-топик.
Сеть: у контейнера раннера pc нет резолва api.telegram.org (URLError мгновенно),
поэтому TG-вызовы уходят через `docker run curlimages/curl` на default bridge,
а файлы — через workdir-volume раннера (имя берётся из docker inspect).
Возврат: 0 = отправлено (SALVAGE=1 в GITHUB_ENV, gen скипается),
1 = файлов нет (нужен полный прогон), 2 = файлы есть, TG не прошёл.
Порядок версий случайный; маппинг пишется в лог задания (не владельцу).
"""
import json
import os
import random
import subprocess
import sys
import urllib.parse
from pathlib import Path

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/xlrun")
FILES = ("sample_A.mp3", "sample_B.mp3", "ce_report.json")
RUNNER = os.environ.get("RUNNER_CONTAINER", "gh-runner-aicontent-factory")
CURL_IMG = "curlimages/curl:8.10.1"


def _sh(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def _work_mount() -> str:
    """-v спецификация для workdir-тома раннера (volume:имя или bind:src)."""
    wd = os.environ.get("RUNNER_WORKDIR") or str(Path.cwd())
    out = subprocess.run(["docker", "inspect", RUNNER, "--format",
                          "{{range .Mounts}}{{.Type}}\\t{{.Name}}\\t{{.Source}}\\t{{.Destination}}\\n{{end}}"],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        t, name, src, dest = (line.split("\\t") + ["", "", ""])[:4]
        if dest and (dest == wd or wd.startswith(dest.rstrip("/") + "/")):
            return (f"{name}:/files:ro" if t == "volume" else f"{src}:/files:ro")
    return ""


def _curl_tg(method: str, fields: list[tuple[str, str]], file_field: tuple[str, Path] | None = None) -> bool:
    """TG Bot API через docker run curl (bridge-сеть раннер-контейнера не резолвит TG)."""
    token, chat = os.environ.get("TG_BOT_TOKEN"), os.environ.get("TG_CHAT_ID")
    if not token or not chat:
        print("TG skip: нет TG_BOT_TOKEN/TG_CHAT_ID")
        return False
    mnt = _work_mount()
    if file_field and not mnt:
        print("TG fail: не нашёл workdir-том раннера для docker run")
        return False
    curl = [f"-X POST {_sh('https://api.telegram.org/bot' + token + '/' + method)}",
            f"-F chat_id={_sh(chat)}"]
    if os.environ.get("TG_THREAD_ID"):
        curl.append(f"-F message_thread_id={_sh(os.environ['TG_THREAD_ID'])}")
    curl += [f"-F {k}={_sh(v)}" for k, v in fields]
    if file_field:
        curl.append(f"-F {file_field[0]}=@/files/{file_field[1].name}")
    cmd = ["docker", "run", "--rm"] + ([f"-v", mnt] if file_field else []) + [CURL_IMG, "sh", "-c",
           "curl -sf -m 120 " + " ".join(curl)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"TG fail: curl rc={r.returncode} {r.stderr[-200:]}")
    return r.returncode == 0


def main() -> int:
    missing = [n for n in FILES if not (SRC / n).is_file()]
    if missing:
        print(f"salvage: нет файлов ({missing}) — нужен полный прогон")
        return 1
    rep = json.loads((SRC / "ce_report.json").read_text())
    order = [("sample_A.mp3", "XL-sft best-of-8"), ("sample_B.mp3", "turbo prod")]
    random.shuffle(order)
    print("BLIND MAP (не для владельца):", {f"Версия {i + 1}": m for i, (f, m) in enumerate(order)})
    ok = True
    for i, (f, m) in enumerate(order):
        ok &= _curl_tg("sendAudio", [
            ("caption", f"Слепой A/B t_b4006a6e — Версия {i + 1}. Какой трек лучше? Ответ: 1 или 2."),
            ("performer", "blind A/B"), ("title", f"versija-{i + 1}")],
            file_field=("audio", SRC / f))
    if ok:
        q = urllib.parse.urlencode({"text": "A/B t_b4006a6e: два трека выше (Версия 1 и Версия 2). "
                                   f"Ответь номером лучше. CE: picked #{rep['picked'] + 1}/{rep['bestof']}, "
                                   f"sec/cand {rep.get('sec_per_cand')}."})
        ok &= _curl_tg("sendMessage", [("text", q)])
    if ok:
        gev = os.environ.get("GITHUB_ENV")
        if gev:
            with open(gev, "a") as fh:
                fh.write("SALVAGE=1\n")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
