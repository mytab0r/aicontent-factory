#!/usr/bin/env python3
"""Шаг 3: lo-fi трек через ACE-Step (HF Space, бесплатный публичный API).

История решения — см. docs/DECISIONS.md п.1 (апдейт):
изначально был чистый numpy-синтез (аккорды на синусах + шум) — качество
признано слабым владельцем ("просто арпеджио+шум, без мелодии/ударных").
Ресёрч актуального рынка (2026): MusicGen — CC-BY-NC (не годится для
монетизации), Stable Audio Open — коммерческая лицензия ОК, но нужна своя
GPU (её нет, 1 vCPU хост). Suno — нет официального API, только
реверс-инженерные обёртки (ToS-риск + юридическая неопределённость вокруг
данных обучения, сейчас в суде с лейблами) — отклонено.

Выбор: ACE-Step (github.com/ace-step/ACE-Step, Apache-2.0, честно заявлен
коммерчески пригодным) через публичный HF Space `ACE-Step/ACE-Step`
(ZeroGPU, бесплатно) по `gradio_client`. Проверено вживую: полный
инструментальный трек 45-60с генерируется за 15-35 секунд (в основном
сетевая/очередная задержка, сама диффузия ~3с) — с большим запасом для
1 видео/день. Жанр-специфичный промпт (не постобработка FFmpeg) даёт
звучание, принятое владельцем после A/B теста 3 вариантов.

ponytail: HF Space — бесплатный общий ресурс без SLA (может тормозить при
чужой нагрузке). Апгрейд при нужде: платный Space/Replicate с тем же
интерфейсом generate_track(), или self-host на домашнем GPU через туннель.
"""
import os
import re
import random
import urllib.error
from pathlib import Path

from gradio_client import Client

import mastering

from common import latest_run_dir

SPACE = "ACE-Step/ACE-Step"

# Под-жанры внутри lo-fi-зонтика — ротация для разнообразия звучания
# (и чтобы не попасть под YouTube spam-policy "identical background music
# across many videos").
# Под-жанры — НЕ ограничено lofi-hip-hop-зонтиком. Конкурентный анализ
# (docs/DECISIONS.md п.5) показал, что самые доходные соседние ниши на
# YouTube (nature ambient, meditation/healing, easy-listening piano) не
# завязаны на lofi-поджанр вообще, и именно они менее насыщены в 2026м,
# чем классический lofi hip-hop. ACE-Step берёт любой текстовый
# жанр-промпт через тот же generate_track() — пайплайн не меняется.
GENRE_PROMPTS = {
    # Одобрен владельцем 13.10 (сэмпл ref1): звучит в паре с ACE15_REF_AUDIO.
    "anime lofi": (
        "dreamy lofi chillout instrumental, bright lush synth pads, sparkling bells and plucks, "
        "soft piano lead melody, warm major seventh chords, gentle laid back beat, deep round bass, "
        "clean polished studio mix, wide stereo, harmonious, uplifting, no vocals"
    ),
    # 16.10 оркестратор (владелец 2 дня без ответа по A/B v1-v3; правило: 0$ и
    # обратимо — решаю сам): направление chill phonk = v2 (I -13.9 ближе всех
    # к цели -14, LRA 1.5 самый плотный; все три в гейте). Промпт = точный
    # v2 из генерации (gen2.py на ПК); "да" владельца 14.10 на направление +
    # "очень неплохо" на master-звук. Переиграет — замена промпта одним коммитом.
    "chill phonk": (
        "chill phonk, wave phonk, late night drive, slow 808 sub bass glide, "
        "heavy punchy kick, crisp trap hi-hats, memphis cowbell lead melody, "
        "dreamy detuned synth pads, airy reverb, soft pitched vocal chops, "
        "sidechain pumping, hypnotic groove, polished modern mix, wide stereo, "
        "instrumental"
    ),
}
# ponytail: 8 жанров из конкурентного анализа (DECISIONS.md п.5) отключены
# из прод-ротации — они никогда не проходили A/B прослушивание владельцем
# (одобрен был только "anime lofi"). Черновики — ниже, в CANDIDATE_GENRE_PROMPTS,
# включать обратно в GENRE_PROMPTS по одному, только после присланного
# семпла и явного одобрения владельцем.
# ponytail: тональности ниже поправлены на major по РЕАЛЬНЫМ измеренным
# данным (tunebat.com, digmyloop.com — аудиоанализ, не стереотип жанра):
# топовый Lofi Girl трек = C#major/82BPM (не A minor, как было изначально);
# Nujabes "Luv(sic)" = F major/92BPM (не F minor). "Минор = меланхолия" был
# моей стереотипной догадкой без проверки, не экспертным выбором. Прод-жанр
# "anime lofi" (GENRE_PROMPTS выше) НЕ тронут здесь намеренно — его смена
# тональности тоже требует нового A/B семпла, не блиц-правки.
CANDIDATE_GENRE_PROMPTS = {
    "jazzhop": (
        "nujabes style lofi hip hop, jazzy piano chords extended m7 maj9, "
        "boom bap swing drums, kick snare groove, warm upright bass, vinyl "
        "crackle, tape saturation, F major, 92 BPM, instrumental, no vocals, "
        "melancholic, dusty texture"
    ),
    "deep focus ambient": (
        "deep focus ambient lofi, slow pads, minimal piano, soft filtered "
        "drums, warm sub bass, vinyl crackle, D minor, 70 BPM, instrumental, "
        "no vocals, spacious, meditative, calm study music"
    ),
    "chillhop": (
        "chillhop, mellow electric piano, laid back boom bap groove, "
        "soulful chords maj7, warm bass, vinyl texture, tape warmth, "
        "C major, 85 BPM, instrumental, no vocals, relaxed, smooth"
    ),
    "rainy night lofi": (
        "rainy night lofi, soft rhodes and muted guitar, slow swung drums, "
        "warm round bass, vinyl crackle, light rain ambience, G minor, "
        "75 BPM, instrumental, no vocals, introspective, cozy, late night"
    ),
    # Ниши из конкурентного анализа (DECISIONS.md п.5), не lofi-derived:
    "nature ambient": (
        "nature ambient soundscape, soft sustained pads, distant birdsong, "
        "gentle flowing water texture, no drums, no percussion, minimal "
        "variation designed to loop seamlessly, warm airy, slow and "
        "unhurried, instrumental, no vocals, relaxing"
    ),
    "meditation healing": (
        "meditation and healing music, slow solo piano phrases with long "
        "decay, soft string pad underneath, 60 BPM, no drums, no vocals, "
        "spacious reverb, calm and grounding, gentle, instrumental"
    ),
    "easy listening piano": (
        "easy listening solo piano, warm and gentle melodic phrases, light "
        "rubato, soft room reverb, no drums, no vocals, 65 BPM, relaxed, "
        "comforting, instrumental"
    ),
    "sleep ambient": (
        "deep sleep ambient, very slow evolving drone pad, no percussion, "
        "no sudden dynamic changes, extremely minimal variation designed to "
        "loop seamlessly, soft low frequencies, instrumental, no vocals, "
        "hypnotic and slow"
    ),
}


def genre_for_mood(mood: str) -> tuple[str, str]:
    """Детерминированный выбор под-жанра по mood (воспроизводимо, но разнообразно)."""
    names = list(GENRE_PROMPTS.keys())
    idx = abs(hash(mood)) % len(names)
    name = names[idx]
    return name, GENRE_PROMPTS[name]


def ace_endpoint() -> tuple[str, str | None]:
    """Endpoint ACE-Step: локальный GPU-ПК (ACE_ENDPOINT) или HF Space.

    Локальный ACE-Step (домашний ПК, RTX 5070 через Tailscale) — тот же
    Gradio-интерфейс и те же параметры, что у HF Space: gradio_client
    совместим, пайплайн не меняется. Локальный вызов без токена.
    """
    local = os.environ.get("ACE_ENDPOINT")
    if local:
        return local, None
    return SPACE, os.environ.get("HF_TOKEN") or None


def generate_track(prompt: str, duration_sec: int, seed: int | None = None,
                   client_cls=Client) -> str:
    """Вызывает ACE-Step, возвращает путь к сгенерированному mp3 (временный файл gradio)."""
    url, token = ace_endpoint()
    try:
        client = client_cls(url, token=token)
    except Exception as e:  # ПК выключен/DNS/туннель — не валим выпуск
        if url == SPACE:
            raise
        print(f"ACE {url} недоступен ({type(e).__name__}: {e}); HF Space фолбэк"[:300])
        client = client_cls(SPACE, token=os.environ.get("HF_TOKEN") or None)
    result = client.predict(
        audio_duration=float(duration_sec),
        prompt=prompt,
        lyrics="[instrumental]",
        infer_step=27,
        guidance_scale=15.0,
        scheduler_type="euler",
        cfg_type="apg",
        omega_scale=10.0,
        manual_seeds=str(seed) if seed is not None else None,
        guidance_interval=0.5,
        guidance_interval_decay=0.0,
        min_guidance_scale=3.0,
        use_erg_tag=True,
        use_erg_lyric=False,
        use_erg_diffusion=True,
        oss_steps=None,
        guidance_scale_text=0.0,
        guidance_scale_lyric=0.0,
        audio2audio_enable=False,
        ref_audio_strength=0.5,
        ref_audio_input=None,
        lora_name_or_path="none",
        api_name="/__call__",
    )
    return result[0]


# ACE-Step 1.5 (MIT): REST API контейнера на ПК. Один вызов до 600с, LM
# планирует структуру, тональность/темп фиксируются -> склеек нет.
ACE15_MAX_SEC = 600
# t_fe1fcf66: 600 с генерация ACE-Step даёт raw LRA 2.3-4.7 LU (плоско), 120 с — 6-9 LU (эталон 5.1).
# Поэтому час-микс собирается из коротких сегментов.
MIX_SEG_SEC = int(os.environ.get("ACE15_MIX_SEG_SEC") or 180)
# сегмент 180 с генерируется ~2 мин; 15 мин без ответа = зависание (21.10), не ждём 40 мин
MIX_TASK_TIMEOUT = int(os.environ.get("ACE15_MIX_TASK_TIMEOUT") or 900)
ACE15_KEYS = ["C major", "F major", "G major", "D major", "A major", "E major"]


def prompt_bpm(prompt: str) -> int | None:
    """t_ef393676: темп задаёт поле bpm, текст «NN BPM» модель игнорирует (ab_1: текст 76,
    поле 89, звучит ~86). Текст промпта = источник истины, иначе seed-формула."""
    m = re.search(r"\b(\d{2,3}) BPM\b", prompt)
    return int(m.group(1)) if m else None


def prompt_key(prompt: str) -> str | None:
    m = re.search(r"\b([A-G][#b]? (?:major|minor))\b", prompt)
    return m.group(1) if m else None


class _Http:
    def __init__(self, base):
        self.base = base.rstrip("/")

    def post(self, path, body, timeout=600):
        import json
        import urllib.request
        r = urllib.request.Request(self.base + path, json.dumps(body).encode(),
                                   {"Content-Type": "application/json"})
        # 600: после рестарта ace-step первый запрос грузит модели >60 с (13.10 TimeoutError)
        return json.load(urllib.request.urlopen(r, timeout=timeout))

    def get(self, path):
        import urllib.request
        return urllib.request.urlopen(self.base + path, timeout=300).read()

    def post_file(self, path, body, field, file_path):
        import json
        import subprocess
        args = []
        for k, v in body.items():
            args += ["-F", f"{k}={str(v).lower() if isinstance(v, bool) else v}"]
        out = subprocess.run(["curl", "-sf", "-m", "120", "-X", "POST", self.base + path,
                              "-F", f"{field}=@{file_path}", *args],
                             capture_output=True, text=True, timeout=600, check=True).stdout
        return json.loads(out)


def ace15_prepare(model: str | None, lora: str | None, api=None) -> dict:
    """t_b4006a6e: LoRA через /v1/lora/load (в /release_task поля LoRA нет). Модель НЕ через /v1/init:
    XL init на 12 ГБ висел 3x1 ч (run 39017603255) -> модель уходит в body запроса (on-demand, run 38971884880).
    Возврат /v1/lora/status — доказательство в лог; LoRA не встала = ошибка шага."""
    if not lora:
        return {}
    import json
    import tempfile
    api = api or _Http(os.environ["ACE15_ENDPOINT"])
    if model:
        # on-demand swap пересоздаёт primary-хендлер (initialize_service) -> LoRA, загруженная ДО swap,
        # теряется. Короткий прогрев моделью: swap в очереди, затем LoRA на уже XL-хендлер.
        # Swap мог не включиться (env воркеров/прочее, прогон 39064436852: "сгенерировала turbo")
        # -> единственный /v1/init с жёстким потолком 900 с (не час, как 39017603255).
        with tempfile.TemporaryDirectory() as td:
            try:
                generate_track_v15("warmup", 10, 0, Path(td) / "w.mp3", api=api, model=model)
            except (RuntimeError, urllib.error.URLError) as e:
                print(f"on-demand swap не сработал ({type(e).__name__}: {e}); /v1/init 900 с", flush=True)
                r = api.post("/v1/init", {"model": model}, timeout=900)
                if r.get("code") != 200 or (r.get("data") or {}).get("loaded_model") != model:
                    raise RuntimeError(f"/v1/init {model}: {str(r)[:300]}") from e
    r = api.post("/v1/lora/load", {"lora_path": lora})
    st = json.loads(api.get("/v1/lora/status"))["data"]
    if r.get("code") != 200 or not (st.get("lora_loaded") and st.get("use_lora")):
        raise RuntimeError(f"LoRA {lora} не подключена: {str(r)[:200]} {st}")
    print(f"ACE15 ready: model={model} lora={lora} status={st}", flush=True)
    return st


def generate_track_v15(prompt: str, duration_sec: int, seed: int, out_path, api=None,
                       poll_sec: float = 5, timeout_sec: int = 2400, ref_audio=None,
                       model: str | None = None) -> dict:
    import json
    import time
    api = api or _Http(os.environ["ACE15_ENDPOINT"])
    body = {"prompt": prompt, "lyrics": "[Instrumental]",
            "audio_duration": min(int(duration_sec), ACE15_MAX_SEC),
            "bpm": prompt_bpm(prompt) or 70 + seed % 21,
            "key_scale": prompt_key(prompt) or ACE15_KEYS[seed % len(ACE15_KEYS)],
            "time_signature": "4", "batch_size": 1, "thinking": True,
            "use_random_seed": False, "seed": seed, "audio_format": "mp3"}
    # t_d53850f6: переделка мелодий чужих треков (cover/repaint/lego) запрещена —
    # эталон задаёт ТОЛЬКО стиль, Content ID матчит каверы и ремиксы.
    assert "task_type" not in body, "task_type (cover/repaint) запрещён в проде"
    m = model or os.environ.get("ACE15_MODEL")  # t_b4006a6e: модель на запрос (XL-sft), пусто = слот контейнера
    if m:
        body["model"] = m
    if ref_audio and Path(ref_audio).is_file():
        # Стиль по эталону (reference_audio): так одобрен звук 13.10.
        tid = api.post_file("/release_task", body, "reference_audio", ref_audio)["data"]["task_id"]
    else:
        tid = api.post("/release_task", body)["data"]["task_id"]
    deadline = time.time() + timeout_sec
    n_poll = 0
    while True:
        d = api.post("/query_result", {"task_id_list": [tid]})["data"][0]
        n_poll += 1
        if d.get("status") != 0 or n_poll % 24 == 0:  # 24×5 c = раз в 2 мин видно, что жив и стоит в очереди
            print(f"  task {tid[:8]} poll#{n_poll}: status={d.get('status')} qpos={d.get('queue_position')}", flush=True)
        if d["status"] != 0:
            break
        if time.time() > deadline:
            raise RuntimeError(f"ACE-Step 1.5 task {tid} timeout")
        time.sleep(poll_sec)
    if d["status"] != 1:
        raise RuntimeError(f"ACE-Step 1.5 task {tid} failed: {str(d.get('result'))[:300]}")
    item = json.loads(d["result"])[0]
    # сервер при неизвестной модели молча берёт primary ("not found ... using primary") — ловим
    if m and item.get("dit_model") and item["dit_model"] != m:
        raise RuntimeError(f"запрошена {m}, сгенерировала {item['dit_model']}")
    Path(out_path).write_bytes(api.get(item["file"]))
    return item


def gated_gen(raw, scores, objective, attempts=3, log=print, extra=0):
    """Гейт сегмента час-микса (t_187762da): качество меряется по КАЖДОМУ сегменту,
    а не только по склейке (17.10: целый час упал на одной полосе 20-60 Гц одного трека).
    best-of-K как PR #59: attempts кандидатов с разными seed, ОДИН батчевый прогон
    критика на сегмент, победитель = MAX CE среди прошедших (objective + CE >= MIN_CE),
    брак удаляется с диска; 0 из attempts -> ещё extra кандидатов (t_f0794976: 3 из 9
    сегментов давали 0/3 при CE 6.13-6.49, порог не снижаем); 0 из всех = None (сегмент
    выкидывается, план проверяет min_sec). Ошибка критика = ошибка шага."""
    from pathlib import Path

    from quality_gate import MIN_CE

    def batch(i, ks, total):
        paths = [raw(i, k) for k in ks]
        ce_list = scores(paths)  # один прогон критика на пачку (модель грузится 1 раз)
        if len(ce_list) != len(paths):
            raise RuntimeError(f"критик вернул {len(ce_list)}/{len(paths)} оценок: {ce_list!r}")
        best, fails = None, []
        for k, p, ce in zip(ks, paths, ce_list):
            why = list(objective(p)) + ([f"CE {min(ce):.2f} < {MIN_CE}"] if min(ce) < MIN_CE else [])
            log(f"сегмент {i} кандидат {k + 1}/{total}: CE(min)={min(ce):.2f}, "
                + ("FAIL: " + "; ".join(why) if why else "OK"))
            if why:
                fails.append(why)
                Path(p).unlink(missing_ok=True)
            elif best is None or min(ce) > best[0]:
                best = (min(ce), p)
        return best, fails

    def gen(i):
        best, fails = batch(i, list(range(attempts)), attempts)
        if best is None and extra > 0:
            best, more = batch(i, list(range(attempts, attempts + extra)), attempts + extra)
            fails += more
        if best is None:
            log(f"сегмент {i}: 0 из {attempts + extra} прошли гейт: " + "; ".join(map(str, fails)))
            return None  # сегмент выбрасывается (план проверит min_sec)
        return best[1]

    return gen


def ace_restart(wait_sec=600):
    """docker restart ace-step + ожидание healthy (как шаг workflow 'ACE-Step up')."""
    import subprocess
    import time
    subprocess.run(["docker", "restart", "ace-step"], check=True, capture_output=True)
    end = time.time() + wait_sec
    while time.time() < end:
        st = subprocess.run(["docker", "inspect", "-f", "{{.State.Health.Status}}", "ace-step"],
                            capture_output=True, text=True).stdout.strip()
        if st == "healthy":
            return
        time.sleep(6)
    raise RuntimeError("ace-step не healthy после рестарта")


def mix_raw(run_dir, prompt, seed, ref, genre_name):
    """Кандидат сегмента час-микса, отмастеренный как прод ДО гейта (ревью t_187762da):
    лофи-мастер (highpass 28 + громкость) меняет полосу 20-60 Гц и LRA — ровно метрики
    провала 17.10, поэтому гейт сегмента обязан мерить мастер, как cand() в best-of."""
    def raw(i, k):
        p = Path(run_dir) / f"mix_{i:02d}_{k}.mp3"
        try:
            generate_track_v15(prompt, MIX_SEG_SEC, seed + i * 100 + k, p, ref_audio=ref,
                               timeout_sec=MIX_TASK_TIMEOUT)
        except RuntimeError as e:
            # t_ffa7ff01: stage=failed = CUDA illegal memory access в LM (лог ace-step 18.10, run 39154188022);
            # контекст CUDA испорчен -> все следующие задачи падают за секунды. Рестарт + 1 повтор.
            # 21.10 run 39536019351: задача висела status=0 40 мин (норма ~2 мин) -> тот же рестарт.
            if "failed" not in str(e) and "timeout" not in str(e):
                raise
            print(f"сегмент {i}/{k}: {str(e)[:160]} -> docker restart ace-step, повтор", flush=True)
            ace_restart()
            generate_track_v15(prompt, MIX_SEG_SEC, seed + i * 100 + k, p, ref_audio=ref,
                               timeout_sec=MIX_TASK_TIMEOUT)
        mastering.master(p, p, genre=genre_name)
        return str(p)
    return raw


def plan_mix(target_sec, gen, dur, budget_sec=1800, max_tracks=12, now=None, min_sec=900,
             max_drops=5):
    """Час-микс из цельных треков 1.5 (модель отдаёт ~482 с вместо 600 — считаем по факту).
    Стоп: набрали target, max_tracks, следующий трек не влезает в бюджет времени шага,
    или max_drops сегментов подряд выбраковал гейт (None). Уже набранное не трогаем.
    Итог < min_sec (15 мин) после выбраковки = ошибка шага, а не короткий выпуск."""
    import time
    now = now or time.monotonic
    start, paths, durs, i, drops = now(), [], [], 0, 0
    while sum(durs) < target_sec and len(paths) < max_tracks and drops < max_drops:
        p = gen(i)
        i += 1
        if p is None:
            drops += 1  # сегмент выбракован: микс дозаполняют другие, порог проверится в конце
        else:
            drops = 0
            paths.append(p)
            durs.append(dur(p))
        # 20.10 run 39353766781: 3 провала подряд обрывали микс на 55-й из 120 мин бюджета.
        # Стоп по бюджету считает ВСЕ попытки (и выбракованные): следующая не влезет -> стоп.
        elapsed = now() - start
        if elapsed + elapsed / i > budget_sec:
            break
    if sum(durs) < min_sec:
        raise RuntimeError(f"микс {int(sum(durs))} с < {min_sec} с (15 мин) после выбраковки "
                           f"сегментов: {len(paths)} трек(ов) — выпуск не состоялся")
    return paths, durs


def _ts(sec: float) -> str:
    s = int(sec)
    h, m, s = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def chapters(durs, names, xfade=0.0) -> list[str]:
    """Главы YouTube: первая 0:00, далее начало каждого трека (каждый стык съедает xfade с)."""
    out, t = [], 0.0
    for d, n in zip(durs, names):
        out.append(f"{_ts(t)} {n}")
        t += d - xfade
    return out


_ADJ = ["Amber", "Velvet", "Paper", "Neon", "Quiet", "Golden", "Misty", "Starlit", "Sleepy", "Candle",
        "Silver", "Rosy", "Hazy", "Pastel", "Lantern", "Moonlit"]
_NOUN = ["Window", "Streetlight", "Rooftop", "Tea", "Rain", "Pages", "Train", "Clouds", "Café", "Notebook",
         "Petals", "Harbor", "Skyline", "Blanket", "Postcard", "Daydream"]


def track_names(n: int, seed: int) -> list[str]:
    import random
    pool = [f"{a} {b}" for a in _ADJ for b in _NOUN]
    return random.Random(seed).sample(pool, n)


def _probe_sec(path) -> float:
    import subprocess
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                 "-of", "csv=p=0", str(path)], capture_output=True, text=True,
                                check=True).stdout)


def chunk_plan(total_sec: int, max_chunk_sec: int = 240) -> list[int]:
    """Разбивает long-form длительность на куски <= max_chunk_sec для ACE-Step
    (один вызов практично ограничен ~240с, см. DECISIONS.md п.5). Короткий
    "сигнатурный" ролик (<= max_chunk_sec) не дробится -- один вызов, как раньше."""
    if total_sec <= max_chunk_sec:
        return [total_sec]
    n = -(-total_sec // max_chunk_sec)  # ceil div
    base = total_sec // n
    chunks = [base] * n
    chunks[-1] += total_sec - base * n  # остаток в последний кусок
    return chunks


XFADE = 16.0  # t_3f0f7b91, t_ffa7ff01: стыки сегментов через acrossfade (шире — плавнее RMS-переход R3), не встык


def seam_times(durs, xfade=XFADE) -> list[float]:
    """Центры кроссфейдов в склейке concat_tracks: их проверяет quality_gate R3 (окно ±5 с, RMS)."""
    return [sum(durs[:i]) - i * xfade + xfade / 2 for i in range(1, len(durs))]


def edge_rms(path, side, sec=5.0) -> float:
    """RMS дБ края сегмента: side='l' начало, 'r' конец (окно sec, как SEAM_HALF гейта R3)."""
    import re
    import subprocess
    dur = _probe_sec(path)
    if side == "body":
        sec = min(sec, dur * 0.4)  # середина без интро/фейда: короткий сегмент не мерим вместе с хвостом
    start = {"r": max(0.0, dur - sec), "body": max(0.0, (dur - sec) / 2)}.get(side, 0.0)  # body = середина
    out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-ss", str(start), "-t", str(sec), "-i", str(path),
                          "-af", "astats=measure_overall=RMS_level:measure_perchannel=none", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    return float(re.findall(r"RMS level dB: (-?[\d.]+|-inf)", out)[-1].replace("-inf", "-120"))


EDGE_RAMP_SEC = 30.0  # gain только на начале сегмента, к телу спадает до 0: без накопления по цепочке
EDGE_MAX_GAIN = 18.0  # 3 прохода x клэмп 6 дБ


def seam_rms(prev, nxt, xfade=XFADE):
    """RMS дБ слева/справа от центра стыка prev->nxt ровно как гейт R3: acrossfade(tri) как в concat_tracks,
    окна [c-SEAM_HALF, c] и [c, c+SEAM_HALF], c = dur(prev) - xfade/2 как в seam_times (t_e0c297c7).
    prev целиком: acrossfade с входом длиной ровно xfade отдаёт пустой поток."""
    import subprocess
    import tempfile
    from quality_gate import SEAM_HALF, rms_db
    with tempfile.TemporaryDirectory() as td:
        x = f"{td}/seam.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(prev), "-t", str(xfade + 2 * SEAM_HALF),
                        "-i", str(nxt), "-filter_complex", f"[0:a][1:a]acrossfade=d={xfade}:c1=tri:c2=tri[a]",
                        "-map", "[a]", "-c:a", "pcm_s16le", x], check=True)
        c = _probe_sec(prev) - xfade / 2
        return rms_db(x, c - SEAM_HALF, SEAM_HALF), rms_db(x, c, SEAM_HALF)


def edge_match(paths, max_gain=6.0, ramp=EDGE_RAMP_SEC, log=print):
    """t_ffa7ff01: acrossfade сглаживает кривые, но не громкость материала: R3-скачки RMS 4-5 дБ (run 39155227095).
    run 39670128584: константный gain на ВЕСЬ сегмент копился по цепочке -> gain только рампой на первые ramp с.
    t_e0c297c7 (runs 40070541695, 40075415222): мерили последние 5 с prev против первых 5 с nxt в сырых файлах,
    а гейт R3 меряет СКЛЕЙКУ: ±5 с от центра 16-с кроссфейда (prev -13..-3 с + nxt 3..13 с с весами tri).
    Удар в начале / брейкдаун перед концом сегмента давал gain не туда (-6.9 дБ) и R3 FAIL. Теперь меряем
    seam_rms — тот же сигнал и те же окна, что гейт. 3 прохода, клэмп ±max_gain на проход."""
    import os
    import subprocess
    gains = [0.0]
    for i in range(1, len(paths)):
        tot = 0.0
        r = max(6.0, min(ramp, _probe_sec(paths[i]) * 0.4))
        for _ in range(3):
            lv, rv = seam_rms(paths[i - 1], paths[i])
            g = max(-max_gain, min(max_gain, lv - rv))
            if abs(g) <= 0.5:
                break
            tmp = f"{paths[i]}.g.mp3"
            af = f"volume='pow(10,{g:.3f}*max(0,1-t/{r:.1f})/20)':eval=frame"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", paths[i], "-af", af,
                            "-c:a", "libmp3lame", "-b:a", "192k", tmp], check=True)
            os.replace(tmp, paths[i])
            tot += g
        gains.append(round(tot, 2))
        log(f"edge_match {i}: gain начала {tot:+.2f} дБ (рампа {r:.0f} с)")
    return gains


def trim_fade_tails(paths, max_sec=20.0, floor_db=6.0, log=print):
    """t_ffa7ff01 (run 39170008194): ACE-Step фейдит конец каждого сегмента; после склейки этот
    хвост-затухание остаётся в середине трека и даёт R3-скачок (тихий хвост -> громкое начало,
    loudnorm не вытягивает 5с-окно целиком). Последний сегмент не трогаем — фейд это нормальный
    конец микса. Срезаем 1с-окна с конца, пока RMS окна ниже медианы тела на floor_db; не более
    max_sec на сегмент. Возвращает список срезанных секунд (по порядку paths)."""
    import os
    import re
    import statistics
    import subprocess
    import tempfile
    cuts = []
    for p in paths:
        dur = _probe_sec(p)
        # metadata=1 кладёт RMS в метаданные кадра, в stderr их нет: без ametadata=print win пуст и срез = no-op
        proc = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error", "-i", p, "-af",
                               "astats=metadata=1:reset=1:measure_overall=RMS_level:measure_perchannel=none,"
                               "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
                               "-f", "null", "-"], capture_output=True, text=True)
        win = [float(x) if x != "-inf" else -120.0
               for x in re.findall(r"RMS_level=(-?[\d.]+|-inf)", proc.stdout)]
        if len(win) < 10:  # тимеровая сетка: короткий/битый файл не режем
            cuts.append(0.0)
            continue
        frame = dur / len(win)  # astats reset=1 -> окно на кадр (~23 мс)
        body = statistics.median(win)
        n = 0
        for r in reversed(win):
            if r > body - floor_db or (n + 1) * frame >= max_sec or (n + 1) * frame > dur * 0.4:
                break
            n += 1
        cut = n * frame
        if cut >= 1.0:
            tmp = f"{p}.trim.mp3"  # рядом с целью: tempfile в /tmp -> OSError 18 cross-device
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", p, "-t", str(dur - cut),
                            "-c:a", "libmp3lame", "-b:a", "192k", tmp], check=True)
            os.replace(tmp, p)
        cuts.append(float(cut))
        log(f"trim_fade_tail {os.path.basename(p)}: -{cut:.0f} с (хвост-затухание)")
    return cuts


def trim_fade_head(paths, max_sec=20.0, floor_db=6.0, log=print):
    """run 40145954650: ACE-Step фейдит и НАЧАЛО сегмента; первым в миксе он даёт тихие блоки 3-63 с ->
    гейт A18 «скачок 4.8 LU между блоками 3 и 63». Зеркало trim_fade_tails: срезаем 1с-окна с НАЧАЛА,
    пока RMS окна ниже медианы тела на floor_db; не более max_sec на сегмент."""
    import os
    import re
    import statistics
    import subprocess
    cuts = []
    for p in paths:
        dur = _probe_sec(p)
        proc = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error", "-i", p, "-af",
                               "astats=metadata=1:reset=1:measure_overall=RMS_level:measure_perchannel=none,"
                               "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
                               "-f", "null", "-"], capture_output=True, text=True)
        win = [float(x) if x != "-inf" else -120.0
               for x in re.findall(r"RMS_level=(-?[\d.]+|-inf)", proc.stdout)]
        if len(win) < 10:
            cuts.append(0.0)
            continue
        frame = dur / len(win)
        body = statistics.median(win)
        n = 0
        for r in win:
            if r > body - floor_db or (n + 1) * frame >= max_sec or (n + 1) * frame > dur * 0.4:
                break
            n += 1
        cut = n * frame
        if cut >= 1.0:
            tmp = f"{p}.h.mp3"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", p, "-ss", str(cut),
                            "-c:a", "libmp3lame", "-b:a", "192k", tmp], check=True)
            os.replace(tmp, p)
        cuts.append(float(cut))
        log(f"trim_fade_head {os.path.basename(p)}: -{cut:.0f} с (вступление-затухание)")
    return cuts

BODY_SEC, BODY_MAX_GAIN, BODY_TOL = 60.0, 6.0, 0.5


def _apply_gain(path, g):
    import os
    import subprocess
    tmp = f"{path}.b.mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-af", f"volume={g:.3f}dB",
                    "-c:a", "libmp3lame", "-b:a", "192k", tmp], check=True)
    os.replace(tmp, path)


def body_lufs(path, sec=BODY_SEC):
    """run 40127996482: body_match мерил RMS, гейт A18 (quality_gate.loudjump_why) меряет медиану short-term
    LUFS (K-weighting). RMS-выровненные тела разошлись на 4.6 LU (блоки 1443/1503/1563 с) -> 03c FAIL.
    Выравниваем той же метрикой, что судит гейт: медиана S (ebur128, шаг 0.1 с) середины сегмента."""
    import re
    import subprocess
    dur = _probe_sec(path)
    sec = min(sec, dur * 0.4)
    start = max(0.0, (dur - sec) / 2)
    out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-ss", str(start), "-t", str(sec), "-i", str(path),
                          "-af", "ebur128=framelog=info", "-f", "null", "-"], capture_output=True, text=True).stderr
    st = sorted(float(x) for x in re.findall(r"S:\s*(-?[\d.]+)", out)[:-1][30:])  # без первых 3 с (окно S)
    return st[len(st) // 2] if st else -120.0


def body_match(paths, log=print):
    """t_cron1024 (run 40075415222): edge_match правит только первые 30 с, тела сегментов из банка
    расходились до 6 дБ -> гейт 03c «скачок громкости 4.9/5.8 LU между блоками». Константный gain
    на сегмент по short-term LUFS середины (body_lufs, метрика гейта A18) к телу первого, клэмп ±BODY_MAX_GAIN. Гейт не ослаблен."""
    ref = body_lufs(paths[0])
    gains = [0.0]
    for p in paths[1:]:
        g = max(-BODY_MAX_GAIN, min(BODY_MAX_GAIN, ref - body_lufs(p)))
        if abs(g) < BODY_TOL:
            g = 0.0
        else:
            _apply_gain(p, g)
        gains.append(round(g, 2))
        log(f"body_match {p}: {g:+.2f} дБ")
    return gains


def prep_segments(paths, log=print):
    """Срез хвостов-затуханий ДО выравнивания краёв. Обратный порядок (run 39326466292): edge_match
    мерил тихий фейд, давил следующие сегменты на -18 дБ, после среза хвоста стык 336 с -> R3 FAIL.
    Фейд последнего сегмента остаётся концом микса."""
    trim_fade_tails(paths[:-1], log=log)
    trim_fade_head(paths, log=log)  # run 40145954650: тихое вступление первого сегмента = A18-скачок в начале
    body_match(paths, log=log)
    return edge_match(paths, log=log)


FADE_END_SEC = 6.0  # A16 (quality_gate.END_DROP 12 дБ): эталоны затухают, ACE-Step/loudnorm обрывают хвост


def fade_end(path, sec: float = FADE_END_SEC) -> None:
    """Затухание последних sec с на месте, длительность не меняется (run 39395729278: резкий конец -9.7 дБ)."""
    import subprocess

    d = _probe_sec(path)
    tmp = str(path) + ".fade.mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-af",
                    f"afade=t=out:st={max(0.0, d - sec):.3f}:d={sec}", "-c:a", "libmp3lame", "-b:a", "192k", tmp],
                   check=True)
    os.replace(tmp, path)


def concat_tracks(paths: list[str], out_path, xfade: float = XFADE) -> None:
    """Склеивает треки цепочкой acrossfade (tri/tri, xfade с): без разрыва громкости и щелчка на стыке."""
    import shutil
    import subprocess

    if len(paths) == 1:
        shutil.copy(paths[0], out_path)
        return
    ins = [x for p in paths for x in ("-i", str(p))]
    fc, prev = [], "[0:a]"
    for i in range(1, len(paths)):
        out = "[a]" if i == len(paths) - 1 else f"[x{i}]"
        fc.append(f"{prev}[{i}:a]acrossfade=d={xfade}:c1=tri:c2=tri{out}")
        prev = out
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *ins, "-filter_complex", ";".join(fc), "-map", "[a]",
                    str(out_path)], check=True, capture_output=True)


def main() -> None:
    import json

    run_dir = latest_run_dir()
    idea = json.loads((run_dir / "idea.json").read_text(encoding="utf-8"))
    mood = idea.get("mood", "cozy lofi")
    ref_override = None  # dd-ветка эталон дня не выбирает

    # Канал-эксперимент (DECISIONS.md п.8): сцена из idea.json -> промпт сцены
    if idea.get("channel") == "dd":
        import dd_channel

        scene_name = idea.get("scene")
        scene = next((s for s in dd_channel.load_scenes() if s["name"] == scene_name), None)
        if scene is None:
            raise SystemExit(f"dd scene not found: {scene_name!r}")
        genre_name, prompt = scene["name"], scene["music_prompt"]
    elif os.environ.get("GENRE"):
        # several videos/day, one per genre (workflow matrix sets GENRE)
        genre_name = os.environ["GENRE"]
        prompt = {**CANDIDATE_GENRE_PROMPTS, **GENRE_PROMPTS}[genre_name]
        # t_d53850f6: сутки-ротация (эталон, промпт-вариант) — треки каждого дня
        # звучат по-разному (пул одобренных 90-с OST-референсов в .state/refpool).
        import sys as _sys
        if str(Path(__file__).parent) not in _sys.path:
            _sys.path.insert(0, str(Path(__file__).parent))
        import refpool
        day_pair = refpool.pick()
        prompt = day_pair["prompt"]
        try:
            refpool.ensure_ref(day_pair)  # качает 90-с клип, если ещё не в кэше
            ref_override = day_pair["ref_path"]
        except Exception as e:  # нет сети/yt-dlp: prod fallback на ACE15_REF_AUDIO (ref1)
            print(f"refpool: эталон дня недоступен ({type(e).__name__}: {e}); fallback ref1")
            ref_override = None
    else:
        genre_name, prompt = genre_for_mood(mood)
        ref_override = None

    # Длительность по умолчанию 60с (сигнатурный клип). Long-form
    # (sleep/meditation/ambient каналы по конкурентному анализу — часто
    # 1-3ч, см. DECISIONS.md п.5) запрашивается через TRACK_DURATION_SEC,
    # дробится chunk_plan() на вызовы ACE-Step <=240с и склеивается
    # concat_tracks() — пайплайн ниже этой строки не меняется.
    duration = int(os.environ.get("TRACK_DURATION_SEC", "60"))

    seed = abs(hash(run_dir.name)) % (2**31)
    ref = ref_override or os.environ.get("ACE15_REF_AUDIO")  # t_d53850f6: пул > фикс-файл

    out_path = run_dir / "track.mp3"
    chaps, seams = [], []
    bestof_meta = None
    if os.environ.get("ACE15_ENDPOINT"):
        ace15_prepare(os.environ.get("ACE15_MODEL"), os.environ.get("ACE15_LORA"))
    if os.environ.get("ACE15_ENDPOINT") and duration > ACE15_MAX_SEC:
        # ресёрч 13.10: хиты ниши 1-4 ч с треклистом; склеиваем ЦЕЛЬНЫЕ разные треки (не куски одного)
        n_seg = int(os.environ.get("ACE15_BESTOF") or 0)  # гейт на сегмент: до N seed'ов, max CE среди прошедших
        mix_budget = int(os.environ.get("ACE15_MIX_BUDGET_SEC") or 7200)

        raw = mix_raw(run_dir, prompt, seed, ref, genre_name)
        if n_seg >= 2:
            from quality_gate import ce_windows_batch, objective

            gen_mix = gated_gen(raw, ce_windows_batch, lambda p: objective(p, genre_name)[0],
                                attempts=n_seg, log=print,
                                extra=int(os.environ.get("ACE15_SEG_EXTRA") or 0))
        else:
            def gen_mix(i):
                return raw(i, 0)

        paths, durs = plan_mix(duration, gen_mix, _probe_sec, budget_sec=mix_budget,
                               max_tracks=-(-duration // MIX_SEG_SEC) + 2)
        prep_segments(paths, log=print)
        durs = [_probe_sec(p) for p in paths]  # срез хвостов меняет длительности — перезамер
        concat_tracks(paths, out_path)
        chaps = chapters(durs, track_names(len(paths), seed), xfade=XFADE)
        seams = seam_times(durs)
        duration = int(sum(durs) - XFADE * (len(durs) - 1))
    elif os.environ.get("ACE15_ENDPOINT"):
        duration = min(duration, ACE15_MAX_SEC)
        n = int(os.environ.get("ACE15_BESTOF") or 0)  # t_b4006a6e: best-of-N через quality_gate, 0 = 1 кандидат
        if n >= 2:
            import bestof
            import shutil
            from quality_gate import ce_windows_batch, objective

            def cand(k):
                c = run_dir / f"cand_{k:02d}.mp3"  # мастерится как прод: гейт меряет то, что уйдёт на канал
                generate_track_v15(prompt, duration, seed + k, c, ref_audio=ref)
                mastering.master(c, c, genre=genre_name)
                return str(c)

            bi, bp, rows = bestof.best_of(n, cand, ce_windows_batch, objective=lambda p: objective(p, genre_name)[0])
            shutil.move(bp, out_path)
            for c in run_dir.glob("cand_*.mp3"):
                c.unlink()  # кандидаты удаляются сразу после выбора (диск)
            bestof_meta = {"n": n, "picked": bi, "model": os.environ.get("ACE15_MODEL"),
                           "lora": os.environ.get("ACE15_LORA"),
                           "cands": [{k: r[k] for k in ("cand", "ce", "fail")} for r in rows]}
        else:
            generate_track_v15(prompt, duration, seed, out_path, ref_audio=ref)
    else:
        chunks = chunk_plan(duration)
        chunk_paths = [
            generate_track(prompt, duration_sec=c, seed=seed + i)
            for i, c in enumerate(chunks)
        ]
        concat_tracks(chunk_paths, out_path)
    # Склейка мастерится повторно сознательно: concat перекодирует и стыкует сегменты, итоговый
    # loudnorm выравнивает громкость часа; этот файл целиком меряют 03c и 04b (гейт выпуска).
    if bestof_meta is None:  # победитель best-of уже отмастерен
        mastering.master(out_path, out_path, genre=genre_name)
    fade_end(out_path)  # после мастеринга: loudnorm подтягивает тихий хвост обратно
    (run_dir / "music_meta.json").write_text(
        json.dumps({"genre": genre_name, "prompt": prompt, "seed": seed, "duration": duration,
                    "chapters": chaps, "seams": seams, "bestof": bestof_meta},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"track -> {out_path} (genre={genre_name}, {duration}s)")


if __name__ == "__main__":
    main()
