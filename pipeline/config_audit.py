#!/usr/bin/env python3
"""G1zm0: еженедельный самоаудит согласованности (t_bb361290, spec t_b4006a6e п.9).

Ловит рассогласование жанр↔мастеринг↔эталон↔пороги ДО выпуска. Только сообщает
(out of scope карточки: значения GENRE_PROMPTS/REF/порогов/цепочек не меняет).

Для каждого жанра GENRE_PROMPTS:
  1. мастеринг-цепочка его профиля ('phonk' в жанре -> phonk-ветка, иначе lofi);
  2. эталон-профиль quality_gate.REF[профиль] с полным набором полос (len == len(BANDS));
  3. порог LRA REF[профиль]['min_lra'].

Sample gate (п.9): файл эталона ref1 (кэш/прод-рецепт daily-video 'reference audio'),
прогнанный через цепочку lofi (mastering.master), проходит objective-гейт quality_gate.
Отсутствие файла = FAIL: прод уйдёт без эталона молча.

Запуск: config_audit.py [--ref /tmp/acf-ref/ref1.wav]
"""
import inspect
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def audit_config(genres, ref, n_bands, chains):
    """Чистая логика (тестируется на подставленных конфигах). Возвращает список проблем."""
    issues = []
    for g in sorted(genres):
        key = "phonk" if "phonk" in g else "lofi"
        if not chains.get(key):
            issues.append(f"{g}: нет мастеринг-цепочки профиля '{key}' (mastering)")
        prof = ref.get(key)
        if not isinstance(prof, dict):
            issues.append(f"{g}: нет эталон-профиля REF['{key}'] (quality_gate.REF)")
            continue
        bands = prof.get("bands")
        if not isinstance(bands, list) or len(bands) != n_bands:
            n = len(bands) if isinstance(bands, list) else 0
            issues.append(f"{g}: REF['{key}']['bands']: {n} полос, гейт меряет {n_bands}")
        if not isinstance(prof.get("min_lra"), (int, float)):
            issues.append(f"{g}: нет порога LRA REF['{key}']['min_lra']")
    return issues


def sample_gate(ref_path):
    """ref1 -> цепочка lofi -> objective. Возвращает (why, metrics) как quality_gate."""
    import mastering
    import quality_gate as qg
    out = str(Path(tempfile.mkdtemp()) / "ref1_lofi.mp3")
    mastering.master(ref_path, out, "anime lofi")
    return qg.objective(out, "anime lofi")


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    ref = argv[argv.index("--ref") + 1] if "--ref" in argv else None

    import importlib.util
    import mastering
    import quality_gate as qg

    spec = importlib.util.spec_from_file_location("music03", Path(__file__).parent / "03_music.py")
    from03 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(from03)
    chains = {"lofi": getattr(mastering, "LOFI_AF", "")}
    src = inspect.getsource(mastering.master)
    chains["phonk"] = src if "phonk" in src and "acompressor" in src else ""

    issues = audit_config(from03.GENRE_PROMPTS.keys(), qg.REF, len(qg.BANDS), chains)
    if ref:
        if not Path(ref).is_file():
            issues.append(f"ref1: файл эталона '{ref}' отсутствует — prod сгенерирует без эталона (ACE15_REF_AUDIO)")
        else:
            why, m = sample_gate(ref)
            print(f"ref1 sample gate: {m}")
            issues += [f"ref1 sample gate (lofi-цепочка): {w}" for w in why]

    for x in issues:
        print(f"::error::config audit: {x}")
    print("audit FAIL" if issues else "audit OK: жанр↔мастеринг↔эталон↔пороги согласованы")
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
