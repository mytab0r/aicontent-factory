# ComfyUI для Wan2.2 FLF2V loop на RTX 50xx (Blackwell sm_120).
# та же причина, что в ../Dockerfile (ACE-Step): нужен torch cu128.
FROM nvidia/cuda:12.8.1-runtime-ubuntu22.04

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    HF_HUB_ENABLE_HF_TRANSFER=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3.10 python3-pip python3-venv git curl ffmpeg \
    && ln -sf /usr/bin/python3 /usr/bin/python \
    && rm -rf /var/lib/apt/lists/*

# root-cause: t_a929cfc3 — pip 22.0.2 из jammy python3-venv не докачивает: обрыв на ~800 MB
# torch-wheel валил слой (TimeoutError). pip>=26.2 докачивает по Range. Гард: pipeline/test_dockerfile_pip_resume.py
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir "pip==26.2.2"
ENV PATH="/opt/venv/bin:$PATH" \
    PIP_RESUME_RETRIES=20

WORKDIR /app
# Пин к известному апстрим-коммиту (main на 2026-10-09)
RUN git clone https://github.com/comfyanonymous/ComfyUI.git /tmp/comfy \
 && git -C /tmp/comfy checkout 926d828e37c6f369a3cf3582887da470f7dab515 \
 && cp -a /tmp/comfy/. /app/ \
 && rm -rf /tmp/comfy/.git /tmp/comfy

# torch-тройка строго из cu128-индекса (sm_120), потом requirements ComfyUI
RUN pip install --no-cache-dir torch torchvision torchaudio \
      --index-url https://download.pytorch.org/whl/cu128 \
 && pip install --no-cache-dir -r requirements.txt

# модель-файлы кладёт владелец/агент в volume comfy-models (см. README)
ENV COMFY_MODEL_PATH=/models
VOLUME /models /app/output /app/input

EXPOSE 8188
CMD ["python", "main.py", "--listen", "0.0.0.0", "--port", "8188", \
     "--extra-model-paths-config", "/models/extra_model_paths.yaml"]
