#!/usr/bin/env python3
"""t_b4006a6e: слепая отправка A/B сэмплов владельцу через TG sendAudio + salvage.

Зачем: Artifact storage quota GitHub исчерпана (пересчёт 6-12 ч), артефакт
gate-samples не грузится. /tmp/xlrun на контейнере раннера pc переживает
прогоны — результаты прошлого прогона спасаем и отдаём в TG-топик.
Сеть: у контейнера раннера pc нет резолва api.telegram.org (URLError мгновенно),
поэтому TG-вызовы уходят через python3 в контейнере ace-step (comfynet, интернет есть),
а аудио-файл — через docker cp в /tmp контейнера.
Возврат: 0 = отправлено (SALVAGE=1 в GITHUB_ENV, gen скипается),
1 = файлов нет (нужен полный прогон), 2 = файлы есть, TG не прошёл.
Порядок версий случайный; маппинг пишется в лог задания (не владельцу).
"""
import json
import os
import random
import subprocess
import sys
from pathlib import Path

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/xlrun")
FILES = ("sample_A.mp3", "sample_B.mp3", "ce_report.json")


def _ace_py(code: str) -> tuple[int, str]:
    cmd = ["docker", "exec", "-i", "ace-step", "python3", "-"]
    r = subprocess.run(cmd, input=code.encode(), capture_output=True, timeout=300)
    return r.returncode, (r.stdout + r.stderr).decode(errors="replace")


def _curl_tg(method: str, fields: list[tuple[str, str]], file_field: tuple[str, Path] | None = None) -> bool:
    """TG Bot API через python3 внутри ace-step (у раннера pc нет резолва TG)."""
    token, chat = os.environ.get("TG_BOT_TOKEN"), os.environ.get("TG_CHAT_ID")
    if not token or not chat:
        print("TG skip: нет TG_BOT_TOKEN/TG_CHAT_ID")
        return False
    if file_field:
        subprocess.run(["docker", "cp", str(file_field[1]), "ace-step:/tmp/ab_file.mp3"], check=True)
    lines = [
        "import json,urllib.request,uuid",
        f"tok={token!r}; chat={chat!r}; method={method!r}",
        "thid = " + repr(os.environ.get("TG_THREAD_ID") or ""),
        f"fields = {fields!r}",
        "b = uuid.uuid4().hex",
        "data = b''",
        "def part(name, val):",
        "    global data",
        "    data += ('--%s\\r\\nContent-Disposition: form-data; name=\"%s\"\\r\\n\\r\\n%s\\r\\n' % (b, name, val)).encode()",
    ]
    for k, v in fields:
        lines.append(f"part({k!r}, {v!r})")
    if os.environ.get("TG_THREAD_ID"):
        lines.append("part('message_thread_id', thid)")
    if file_field:
        lines += [
            "data += ('--%s\\r\\nContent-Disposition: form-data; name=\"audio\"; filename=\"ab.mp3\"\\r\\nContent-Type: audio/mpeg\\r\\n\\r\\n' % b).encode() + open('/tmp/ab_file.mp3','rb').read() + b'\\r\\n'",
        ]
    lines += [
        "data += ('--%s--\\r\\n' % b).encode()",
        "req = urllib.request.Request('https://api.telegram.org/bot' + tok + '/' + method, data=data, headers={'Content-Type': 'multipart/form-data; boundary=' + b})",
        "urllib.request.urlopen(req, timeout=120).read()",
        "print('TG OK', method)",
    ]
    rc, out = _ace_py("\n".join(lines))
    if rc != 0:
        print(f"TG fail: {out[-300:]}")
    return rc == 0


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
        ok &= _curl_tg("sendMessage", [(
            "text", "A/B t_b4006a6e: два трека выше (Версия 1 и Версия 2). "
            f"Ответь номером лучше. CE: picked #{rep['picked'] + 1}/{rep['bestof']}, "
            f"sec/cand {rep.get('sec_per_cand')}.")])
    if ok:
        gev = os.environ.get("GITHUB_ENV")
        if gev:
            with open(gev, "a") as fh:
                fh.write("SALVAGE=1\n")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
