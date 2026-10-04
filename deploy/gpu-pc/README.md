# Развертывание ACE-Step на GPU-ПК (Windows + Docker Desktop с GPU)

Полностью в контейнере: ничего не ставится в систему, весь мусор — внутри
образа и в одной папке данных. Первый старт качает модель (~8 GB) в
`ace-data/checkpoints` и поднимается за 5-10 мин.

## Предварительно (один раз, вне контейнера — это нельзя контейнеризовать)
1. **Docker Desktop** для Windows с WSL2-бэкендом: https://www.docker.com/products/docker-desktop/
   В Settings → General включено `Use WSL 2 based engine` (по умолчанию так).
   GPU работает из коробки при свежем NVIDIA-драйвере (проверить: `docker run --rm --gpus all nvidia/cuda:12.8.1-runtime-ubuntu22.04 nvidia-smi`).
2. **Tailscale**: https://tailscale.com/download/windows → `tailscale up` →
   записать IP машины (`tailscale ip -4`, вид 100.x.y.z).

## Развертывание (PowerShell, одна сессия)
```powershell
git clone https://github.com/mytab0r/aicontent-factory
cd aicontent-factory
mkdir ace-data\checkpoints, ace-data\outputs, ace-data\logs -Force
docker compose -f deploy/gpu-pc/docker-compose.yml up -d --build
```

## Проверка (агент выполняет по порядку, стоп на первой ошибке)
```powershell
# 1. Контейнер жив и здоров (ждать health=healthy, первый старт долгий)
docker ps --filter name=ace-step --format "{{.Status}}"
# 2. GPU виден внутри контейнера
docker exec ace-step nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
# ожидание: NVIDIA GeForce RTX 5070, 12288 MiB
# 3. Модель скачалась (появились файлы чекпоинта)
docker exec ace-step ls /app/checkpoints
# 4. HTTP отвечает
curl.exe -s -o NUL -w "%{http_code}" http://localhost:7865/
# ожидание: 200
```

## Проверка генерации (финальный гейт)
```powershell
uv venv .venv-gradio; .venv-gradio\Scripts\activate
uv pip install gradio_client
python -c "
from gradio_client import Client, handle_file
c = Client('http://localhost:7865/')
r = c.predict(audio_duration=30.0, prompt='anime lofi, soft rhodes piano melody, gentle boom bap drums, warm bassline, vinyl noise, A minor, 82 BPM, instrumental, no vocals', lyrics='[instrumental]', infer_step=27, guidance_scale=15.0, scheduler_type='euler', cfg_type='apg', omega_scale=10.0, manual_seeds='42', guidance_interval=0.5, guidance_interval_decay=0.0, min_guidance_scale=3.0, use_erg_tag=True, use_erg_lyric=False, use_erg_diffusion=True, oss_steps=None, guidance_scale_text=0.0, guidance_scale_lyric=0.0, audio2audio_enable=False, ref_audio_strength=0.5, ref_audio_input=None, lora_name_or_path='none', api_name='/__call__')
print('OK', r)
"
```
Появился mp3-путь в выводе → генерация работает. Файл лежит в `ace-data/outputs/`.

## Финал
Сообщить владельцу tailnet-IP (100.x.y.z). В GitHub Secret `ACE_ENDPOINT`
прописывается `http://100.x.y.z:7865` — пайплайн начнёт ходить на локальную
GPU, HF Space остаётся фолбэком.

## Что где
- Модель/выводы/логи: `ace-data/` рядом с репо — удаляется одной папкой.
- Firewall: наружу порт не открыт (bind 127.0.0.1 + Tailscale — доступ только
  из твоей tailnet-сети). Открывать ничего в роутере не нужно.
- Обновление модели/кода: `git pull && docker compose ... up -d --build`.
