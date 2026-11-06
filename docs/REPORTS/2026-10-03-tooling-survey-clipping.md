# Tooling survey: automated clipping / short-form repurposing for faceless music content (2024-2026)

Context: aicontent-factory - static/looping background art + instrumental music, no speech, no faces.
FFmpeg already in the pipeline. Commercial licensing mandatory. Question: reuse an existing
clipper/repurposer or build on the current FFmpeg pipeline?

## Key finding

The whole 2025-2026 wave of open-source Opus Clip clones is transcript-first:
Whisper -> LLM picks "viral moments" from speech -> face-tracking reframe to 9:16 [18][20][21][22][23].
That segmentation brain is exactly the part aicontent-factory does not need. For continuous
instrumental music there are no speech highlights and no faces. Real problems are:
(a) where to cut (visual/audio energy boundaries), (b) 9:16 reframe (trivial ffmpeg crop/scale),
(c) hook text overlay (one drawtext filter), (d) multi-platform posting (OAuth pain, not clipping).
No surveyed tool solves (a)-(c) better than ~50 lines of Python+FFmpeg the project does not
already have. Conclusion: steal parts, not tools.

## Survey table

| Tool | License | Fits faceless music? | Self-host | Setup | Verdict |
|---|---|---|---|---|---|
| OpenShorts (mutonby/openshorts, ~5.9k stars, active) | MIT [18] | Partial: explicit silent-video fallback (NoAudioError -> get_visual_clips, Gemini vision) [18] | Yes, Docker, 8GB+ RAM; CPU = 5-8 min per 8-min video [19] | High | Reference only, do not deploy |
| SupoClip | AGPL-3.0 [20] | No (speech + face crop) | Yes | High | Avoid: AGPL network copyleft + N/A |
| ClipPro | not verified (repo 404s today) [21] | No (Whisper transcript-first) | Yes | Med | N/A + likely abandoned |
| ClipForge (desktop app) | MIT [22] | No (face + active-speaker reframe core) | Desktop | Med | N/A |
| OpenClipper (Windows desktop) | MIT [23] | No (face autoreframe) | Desktop | Low | N/A |
| Shaddai Clipper | MIT per README (repo now 404s) | No (vocal-energy scoring) | Yes | Med | N/A + gone |
| auto-editor (~5.4k stars, active) | Unlicense / public domain [24] | Wrong model: cuts silence; continuous music has none | CLI | Trivial | Keep in pocket only |
| PySceneDetect (~5.2k stars, v0.7.1 2026-07, active) | BSD-3-Clause [26] | YES: scene/cut-point detection, ffmpeg split, Docker image | pip install | Low | USE - only worthwhile component |
| short-video-maker (~1.4k stars) | MIT [25] | No: TTS-narrated short generator (Kokoro TTS + Whisper + Pexels + Remotion) | Docker | Med | Skip |
| n8n + faceless templates | n8n sustainable-use; templates are generate-from-scratch (Sora2 [28]; Sheets->PiAPI->Kling->ElevenLabs->Creatomate->upload-post [27]) | Not clippers | Yes | Med-High | Skip: redundant next to Python+Actions |
| Upload-Post (SaaS posting API) | Proprietary SaaS [29] | Content-agnostic posting to 22 platforms, official OAuth | No | Low | Consider for TikTok/IG only |
| audiospectr | MIT [31] | YES: audio-reactive visualizer over background image, ships examples/lofi-ambient.json preset | pip + ffmpeg | Low | Use/reference |
| audioviz-cli | MIT [33] | Yes: JSON-config music video renderer, spectrum + text overlays | pip + ffmpeg | Low | Reference |
| klangbild | GPL-3.0 [32] | Content fits (4K music visualizer) | CLI | Low | External-binary use only (subprocess); never link as a library |
| QCut | NO license found [30] | - | - | - | Unusable commercially |

## Notes

- OpenShorts: MIT core; pipeline yt-dlp -> faster-whisper -> PySceneDetect -> Gemini moment pick ->
  ffmpeg cut -> MediaPipe/YOLO reframe -> hook overlays -> Upload-Post publishing [18]. It is the
  only surveyed clipper with a no-audio visual path, but it wants 8GB RAM and its "visual moment
  detection" adds nothing for static Ken Burns art vs plain timestamp sampling. Read hooks.py for
  overlay rendering ideas (MIT, copy freely); do not run on the 1 vCPU/957MB server [19].
- PySceneDetect: the one real reuse. Run AdaptiveDetector over existing long-form renders to find
  clean cut points (segment end / after crossfade) instead of arbitrary timestamps. Light on CPU,
  fine on the 1 vCPU box and in GitHub Actions [26]. Fully static single-scene renders -> fixed
  interval cuts instead.
- auto-editor: public domain, zero license risk, but its value prop (cut dead air) does not exist
  in continuous music. One `silencedetect`+`trim` ffmpeg line covers lead-in/out trimming anyway [24].
- short-video-maker: MIT wrapper but renders through Remotion, whose custom license is free only
  for individuals/small companies; larger for-profit orgs need a paid company license [9][25].
  Any Remotion-based tool inherits that question. Skip.
- Upload-Post: free tier 10 uploads/mo (no TikTok), Basic ~$16/mo annual unlimited, official API
  OAuth flows handled [29]. Only "buy" worth considering, and only if auto-posting to TikTok/IG is
  actually needed; YouTube Data API direct is fine and free (quota-capped).
- audiospectr (MIT): pre-analyzes audio to FFT/waveform/RMS frames, composites RGBA visualizer
  layers over a background image, streams frames to ffmpeg, has a lofi-ambient preset (circular
  ring + ember particles over dimmed blurred bg). Closest content-shape match to this project [31].

## Recommendation

Build, do not adopt. Existing pipeline is ~80% of the answer.

1. REUSE: PySceneDetect (BSD-3-Clause) - only off-the-shelf component worth adding; cut-point
   detection over existing renders; afternoon-scale glue (~50 lines), no new services, no GPU [26].
2. REUSE/REFERENCE: audiospectr (MIT) for audio-reactive motion in vertical teasers, or as direct
   renderer if its style fits [31].
3. PLAIN FFMPEG for the rest (already installed):
   - 9:16: `scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920` (or blur-pad)
   - hook text: `drawtext` + `enable='between(t,0,3)'`
   - teaser segment choice: loudest 30-60s window via `ebur128`/`astats` scan (replaces "viral
     moment detection" for music)
4. SKIP: SupoClip (AGPL [20]); short-video-maker / anything Remotion-based (paid license above
   small-company size [9][25]); ClipForge, OpenClipper (face cores [22][23]); ClipPro/Shaddai
   (speech-based, one 404s); QCut (no license [30]); n8n (redundant infra).
5. POCKET: auto-editor (public domain) for asset silence trims; OpenShorts hooks.py as MIT
   reference for fancier hook overlays [18][24].
6. POSTING: YouTube Data API direct; add Upload-Post ~$16/mo only when TikTok/IG auto-post
   becomes real [29].

License/star/activity data cross-checked via GitHub API on 2026-10-03.

## Sources

- [9] https://github.com/remotion-dev/remotion/blob/main/LICENSE.md - Remotion License
- [18] https://github.com/mutonby/openshorts
- [19] https://www.openshorts.app
- [20] https://github.com/FujiwaraChoki/supoclip
- [21] https://github.com/chang-pro/clippro
- [22] https://github.com/JeremySNR/clip-forge
- [23] https://github.com/GrepCut/OpenClipper
- [24] https://github.com/wyattblue/auto-editor
- [25] https://github.com/gyoridavid/short-video-maker
- [26] https://github.com/breakthrough/pyscenedetect
- [27] https://n8n.io/workflows/3442-fully-automated-ai-video-generation-and-multi-platform-publishing/
- [28] https://n8n.io/workflows/10455-generate-and-publish-ai-faceless-videos-to-youtube-shorts-using-sora-2/
- [29] https://www.upload-post.com
- [30] https://github.com/Quriosity-agent/qcut
- [31] https://github.com/bradsec/audiospectr
- [32] https://github.com/skvggor/klangbild
- [33] https://github.com/jschm42/audioviz-cli
- [1] https://www.ffmpeg.org/ffmpeg-filters.html
