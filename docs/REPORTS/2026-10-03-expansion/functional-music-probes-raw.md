# Raw evidence: YouTube autocomplete + search supply probes (2026-10-03)

Method: YouTube autocomplete via suggestqueries.google.com (ds=yt) = live demand signal.
YouTube search results scrape (ytInitialData) = live supply signal. Google Trends (pytrends)
= multi-year interest curves. All queries in English, US locale.

## Autocomplete depth (number of distinct completions) as demand proxy

| Query stem | Completions | Notable |
|---|---|---|
| music for | 10 | studying, sleep, work, meditation, gym, kids, reading, **cats**, relaxation |
| sleep music for | 10 | **kids, cats, babies, deep sleep, toddlers, dreams, insomnia, children, dog** |
| sleep music for dogs | 6 | incl. "no ads", "and humans", "black screen" |
| adhd focus music techno | 1 | niche but real (exists as completion) |
| brown noise | 10 | for studying, sleep, focus, **adhd**, **pomodoro**, 8 hours |
| green noise | 10 | for studying, sleeping 10 hours, music, meditation |
| dnd music | 10 | forest, night, home, tavern, **vampire**, boss fight, camp, town |
| fantasy tavern | 10 | music, asmr, minecraft, playlist, **lofi** |
| cozy game music | 10 | playlist, no copyright, soundtrack, board game, indie |
| organic house mix | 10 | incl. **2025 / 2024 / 2026** year-stamped — active trend |
| adhd music | 10 | **8d**, techno, upbeat, "for concentration upbeat" |
| focus music | 10 | adhd, binaural beats, **trading**, **deep house** |
| witchy ambience | 10 | no ads, asmr, sleep |
| gothic ambience | 10 | rain, no ads, no music, sleep |
| black screen sleep | 10 | space, rain and thunder, no ads |
| sleep music | 10 | **no ads**, black screen, frequency, cats |
| reading music | 10 | **"reading music no ai"** (!) |
| coding music | 10 | **"coding music no ai"** (!), 2025 |
| library ambience | 10 | pomodoro, no ads, study with me |
| snowstorm ambience | 10 | cabin, dnd, jazz |
| music for dogs | 10 | "during **fireworks**", "no ads", "home alone" |

Key signal: **"no ads" appears as an autocomplete modifier in nearly every
functional-music stem** — a quality complaint YouTube's ad loads created, and an
incumbent weakness (ads mid-sleep-video destroy the use case).

## Google Trends (pytrends, 2021-09 → 2026-10, yearly means, 0-100 within each set)

Set 1: green noise / dungeon synth / sleep music for dogs / organic house / lofi hip hop
- green noise: 3 (2022) → 15.5 (Q1 2024) → 29.5 (Q1 2026) → **61.5 (Q2 2026)**
- organic house: 4.2 flat 2022-2024 → 5.6 (2025) → **17.2 (Q3 2025), 29.7 (Q1 2026), 66.8 (Q2 2026)**
- dungeon synth: 9 (2022) → 14 → 17 → 23.5 → 26 → 28.5 (2026) — steady growth, never spiked
- lofi hip hop: 35 (2022) → 56 (2023 peak) → **33→20 decline 2024-2026**
- sleep music for dogs: 0 until 2025, 0.3 (2025) → **1.0 (Q2 2026)** (absolute small, but from zero)

Set 2: dungeon synth 28.5 / dnd music 75.6 (2026, up from 23 in 2022) / fantasy ambience
0.3→6.8 (2025→2026) / skyrim ambience stable small

Set 3: study music 3 (2022) → 6.9 (2023) → **35.2 (2025) → 57.6 (2026, huge rise)**
- coding music: 0.1 (2022-24) → 1.9 (2025) → 6.5 (2026)
- black screen sleep: 0 → 2.2 (2026)

Set 4: witchy music 0 → 0.7 (2026); space ambient 2 → 3 → 6.7 (2025) → **13.5 (2026)**
- synthwave stable ~23-36; dark academia declining 93→52

Set 5: **ambient music 2.0 (2022) → 9.0 (2026, 4.5x)**; **lofi 54.7 (2023 peak) → 33.2
(2026, -40%)**; classical music 26 → 54.9 (more than doubled); jazz 14 → 26.7

## YouTube search supply scrape (top-10 results per query, 2026-10-03)

"adhd focus music techno" — supply is ONE creator (Jason Lewis - Mind Amend) with 6 of
10 top results, videos 160K-1M views, newest 8 months old; one 1-month-old new entrant
at 230 views. Demand exists (autocomplete + Trends rise), supply near-monoculture, ageing
incumbent format (isochronic tones branding).

"sleep music for dogs black screen" — top videos 100K-1.2M views; strongest ("Music for
dogs" 1.2M) is **5 years old**; Merlin's Realms videos 2-5 years old. Supply old, small
channels (24-63K subs). Trend rising from zero in 2026.

"dnd tavern music" — #1 result 11.2M views is **5 years old** (Daydreaming of
Persephone); Bardify videos 4 years old; a fresh upload (8mo) gets 1.3M (The Singing
Tavern) — demand still arriving for fresh content. "dnd tavern music no ai" is an
autocomplete completion.

"cozy game music" — top results are Nintendo/IP compilations (Fancy Fox Gaming 1.6M
stream, 2y old; stellarsheik 5y old). No branded "cozy game music radio" channel
incumbent. Copyright risk flag on actual game OSTs.

"organic house mix" — fragmented supply: GUGB Music 336K (8mo), Peripheral Vinyl
Sessions 325K (1y), no dominant functional channel; Cafe De Anatolia is the biggest
brand but positions as world/ethnic label, not functional/work music.

"space ambient sleep" — Celestial Ambience 23.9M views video is 5y old; View Escape
2.5M 1y ago; demand high, supply mostly old mega-videos or tiny new channels.

"green noise sleep" — top video 12.8M views 3y old, several 5-6y old mega-videos; new
channels rare. Demand exploded AFTER most supply was uploaded (supply quality low:
literally static + black screen).

"lofi hip hop beats to relax study to" — wall of Lofi Girl/Chillhop incumbents incl.
fresh clones with 0-13 views (DreamHop Studio, 1h old). Confirms hyper-oversupply.

"cat music" — search polluted: "Cat Music" is a Romanian pop LABEL (53M-view pop
videos). Actual functional cat music (Cats Only Channel 16.5M, 4y old; Relax My Cat
24M, 8y old) is old. Species-specific music (David Teie approach) is scientifically
supported but barely represented on YouTube. Search intent collision = opportunity for
clearly-branded channel.
