#!/usr/bin/env python3
"""t_b4006a6e, run 198: обойти Artifact storage quota GitHub (пересчёт 6-12 ч).

Результаты прогона 8 лежат на диске раннера ПК (/tmp/xlrun): ce_report.json,
sample_A.mp3 (XL best-of-8), sample_B.mp3 (prod turbo), .labels.json.
Запуск на ПК: python3 fetch_xlrun.py <workspace_dir> [/tmp/xlrun]
Копирует результаты в канбан-workspace (их приложу к карточке) и шлёт
слепой A/B владельцу в TG-топик quality_gate (sendAudio через Bot API).
"""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import tg_send  # noqa: E402

WS = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
SRC = Path(sys.argv[2] if len(sys.argv) > 2 else "/tmp/xlrun")


def tg_send_file(path: Path, caption: str) -> bool:
    """sendAudio в TG-топик (TG_BOT_TOKEN/TG_CHAT_ID[/TG_THREAD_ID])."""
    import os
    import urllib.parse
    import uuid
    token, chat = os.environ.get("TG_BOT_TOKEN"), os.environ.get("TG_CHAT_ID")
    if not token or not chat:
        print("TG skip: нет TG_BOT_TOKEN/TG_CHAT_ID")
        return False
    boundary = uuid.uuid4().hex
    parts = [("chat_id", chat), ("caption", caption), ("performer", "A/B")]
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
        urllib.request.urlopen(req, timeout=60)
        return True
    except Exception as e:
        print(f"TG fail: {type(e).__name__}")
        return False


def main() -> int:
    missing = [n for n in ("sample_A.mp3", "sample_B.mp3", "ce_report.json") if not (SRC / n).is_file()]
    if missing:
        print(f"нет файлов на раннере: {missing}")
        return 1
    WS.mkdir(parents=True, exist_ok=True)
    for n in ("sample_A.mp3", "sample_B.mp3", "ce_report.json"):
        (WS / n).write_bytes((SRC / n).read_bytes())
    print("copied:", sorted(p.name for p in WS.iterdir()))
    rep = json.loads((SRC / "ce_report.json").read_text())
    ok = True
    for n, cap in (("sample_A.mp3", "Версия 1"), ("sample_B.mp3", "Версия 2")):
        ok &= tg_send_file(WS / n, f"Слепой A/B t_b4006a6e: {cap}. Какой трек лучше? Ответ: 1 или 2.")
    if ok:
        tg_send(f"Слепой A/B t_b4006a6e отправлен двумя сообщениями выше. "
                f"best-of-8 XL-sft: picked #{rep['picked'] + 1}, CE {rep['ce']}")
    else:
        print("sendAudio не прошёл — файлы лежат в workspace, вложу в канбан-карточку")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
