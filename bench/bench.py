"""Benchmark our samples against top-viewed YouTube references per format.
Fit = share of features inside the reference p10..p90 band. ponytail: hand-picked features, not a learned
quality score; add CLAP/MERT embedding similarity when features stop separating good from bad."""
import json, os, subprocess, glob
import numpy as np, librosa
FORMATS = {
 "slow": ["calm piano background music", "relaxing music box music", "soft ambient piano music for studying",
          "cozy background music for cafe", "gentle piano music for sleep"],
 "up":   ["melodic bass mix female vocals", "melodic dubstep chill mix", "chill future bass mix",
          "seraphine k/da song", "uplifting melodic bass music"],
}
OURS = {"slow": ["S1", "S2", "S3", "S1b"], "up": ["U1", "U2", "U1b"]}
TOP, MIN_VIEWS = 8, 1_000_000
YT = "/tmp/ytv/bin/yt-dlp"

def search(q):
    out = subprocess.run([YT, "--flat-playlist", "-J", f"ytsearch20:{q}"], capture_output=True, text=True).stdout
    return json.loads(out).get("entries", []) if out else []

def pick(fmt):
    seen = {}
    for q in FORMATS[fmt]:
        for e in search(q):
            v, d = e.get("view_count") or 0, e.get("duration") or 0
            if v >= MIN_VIEWS and d >= 120 and e["id"] not in seen:
                seen[e["id"]] = dict(id=e["id"], title=e.get("title"), views=v, dur=d, q=q)
    return sorted(seen.values(), key=lambda x: -x["views"])[:TOP]

def fetch(ref):
    wav = f"refs/{ref['id']}.wav"
    if os.path.exists(wav): return wav
    for c in ["default", "android", "tv", "web_safari", "mweb"]:
        subprocess.run(["sh", "-c", f"rm -f refs/raw_{ref['id']}.*"])
        if subprocess.run([YT, "-q", "-f", "bestaudio", "--extractor-args", f"youtube:player_client={c}",
                           "-o", f"refs/raw_{ref['id']}.%(ext)s", f"https://youtu.be/{ref['id']}"]).returncode == 0: break
    raw = glob.glob(f"refs/raw_{ref['id']}.*")
    if not raw: return None
    ss = max(0, int(ref["dur"]) // 2 - 45)  # 90 s from the middle: skip intros/outros
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", str(ss), "-t", "90", "-i", raw[0], "-ac", "1", "-ar", "22050", wav])
    os.remove(raw[0]); return wav if os.path.exists(wav) else None

def lufs(path):
    o = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af", "ebur128", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    g = lambda k: float(o.rsplit(k, 1)[1].split()[0])
    return g("I:"), g("LRA:")

def feats(path):
    y, sr = librosa.load(path, sr=22050, mono=True, duration=90)
    S = np.abs(librosa.stft(y)) ** 2; f = librosa.fft_frequencies(sr=sr)
    tot = S.sum() + 1e-12
    tempo = float(np.atleast_1d(librosa.beat.beat_track(y=y, sr=sr)[0])[0])
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr).mean(1); chroma /= chroma.sum()
    h, p = librosa.effects.hpss(y)
    I, LRA = lufs(path)
    return {
        "tempo": tempo, "loudness_lufs": I, "dynamics_lra": LRA,
        "brightness_hz": float(librosa.feature.spectral_centroid(S=np.sqrt(S), sr=sr).mean()),
        "bass_share": float(S[f < 150].sum() / tot),
        "air_share": float(S[f > 6000].sum() / tot),
        "onsets_per_s": float(len(librosa.onset.onset_detect(y=y, sr=sr)) / (len(y) / sr)),
        "percussive_share": float((p ** 2).sum() / ((h ** 2).sum() + (p ** 2).sum() + 1e-12)),
        "tonal_clarity": float(chroma.max() - np.median(chroma)),   # low = muddy / out-of-key smear
        "noisiness": float(librosa.feature.spectral_flatness(y=y).mean()),
    }

def main():
    os.makedirs("refs", exist_ok=True); os.makedirs("out", exist_ok=True)
    report = {}
    for fmt in FORMATS:
        rows = []
        for ref in pick(fmt):
            w = fetch(ref)
            if w: rows.append(dict(ref, **feats(w))); print(fmt, ref["views"], ref["title"], flush=True)
        keys = [k for k in rows[0] if k not in ("id", "title", "views", "dur", "q")]
        band = {k: (float(np.percentile([r[k] for r in rows], 10)), float(np.percentile([r[k] for r in rows], 90)),
                    float(np.median([r[k] for r in rows]))) for k in keys}
        ours = []
        for tag in OURS[fmt]:
            m = glob.glob(f"bench/ours/{tag}_*.mp3")
            if not m: continue
            x = feats(m[0]); inside = {k: band[k][0] <= x[k] <= band[k][1] for k in keys}
            ours.append(dict(tag=tag, file=os.path.basename(m[0]), fit=round(sum(inside.values()) / len(keys), 2),
                             off={k: [round(x[k], 3), [round(band[k][0], 3), round(band[k][1], 3)]] for k in keys if not inside[k]},
                             **{k: round(v, 3) for k, v in x.items()}))
        report[fmt] = dict(refs=rows, band={k: [round(v, 3) for v in b] for k, b in band.items()}, ours=ours)
        for o in ours: print(fmt, o["tag"], "fit", o["fit"], "off", o["off"], flush=True)
    json.dump(report, open("out/bench.json", "w"), indent=1, ensure_ascii=False, default=float)

if __name__ == "__main__":
    main()
