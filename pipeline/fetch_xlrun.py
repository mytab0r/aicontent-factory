#!/usr/bin/env python3
"""t_b4006a6e: слепая отправка A/B сэмплов владельцу через TG sendAudio + salvage.

Зачем: Artifact storage quota GitHub исчерпана (пересчёт 6-12 ч), артефакт
gate-samples не грузится; /tmp/xlrun на раннере persists между запусками
контейнера — результаты прошлого прогона спасаем и отдаём в TG-топик.
Возврат: 0 = отправлено (в GITHUB_ENV пишется SALVAGE=1, gen можно скипнуть),
1 = файлов нет (прогон обязан сгенерить заново), 2 = файлы есть, TG не прошёл.
Порядок версий в сообщениях случайный, маппинг пишется в лог задания.
"""
import json
import os
import random
import sys
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import tg_send  # noqa: E402

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/xlrun")
FILES = ("sample_A.mp3", "sample_B.mp3", "ce_report.json")


def tg_send_file(path: Path, caption: str) -> bool:
    token, chat = os.environ.get("TG_BOT_TOKEN"), os.environ.get("TG_CHAT_ID")
    if not token or not chat:
        print("TG skip: нет TG_BOT_TOKEN/TG_CHAT_ID")
        return False
    boundary = uuid.uuid4().hex
    parts = [("chat_id", chat), ("caption", caption[:1000]), ("performer", "blind A/B"), ("title", path.stem)]
    if os.environ.get("TG_THREAD_ID"):
        parts.append(("message_thread_id", os.environ["TG_THREAD_ID"]))
    body = b""
    for k, v in parts:
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"{path.name}\"\r\n"
             "Content-Type: audio/mpeg\r\n\r\n").encode() + path.read_bytes() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendAudio", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        urllib.request.urlopen(req, timeout=120)
        return True
    except Exception as e:
        print(f"TG fail: {type(e).__name__}")
        return False


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
        ok &= tg_send_file(SRC / f, f"Слепой A/B t_b4006a6e — Версия {i + 1}. Какой трек лучше? Ответ: 1 или 2.")
    if ok:
        tg_send(f"A/B t_b4006a6e: два трека выше (Версия 1 и Версия 2). Ответь номером лучше. "
                f"CE отчёт: picked #{rep['picked'] + 1}/{rep['bestof']}, sec/cand {rep.get('sec_per_cand')}.")
        gev = os.environ.get("GITHUB_ENV")
        if gev:
            with open(gev, "a") as fh:
                fh.write("SALVAGE=1\n")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
