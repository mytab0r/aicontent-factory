# ACE-Step GPU-сервер для RTX 50xx (Blackwell).
# Почему не официальный образ ace-step: он на cu126/torch из requirements —
# sm_120 не поддерживает (подтверждено мантейнерами PyTorch: Blackwell
# поддержан с torch 2.7.0 на билдах CUDA 12.8+). Поэтому cu128-база и torch
# из cu128-индекса ДО общих requirements.
FROM nvidia/cuda:12.8.1-runtime-ubuntu22.04

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    HF_HUB_ENABLE_HF_TRANSFER=1 \
    ACE_OUTPUT_DIR=/app/outputs

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3.10 libpython3.10 python3-pip python3-venv git curl ffmpeg \
    && ln -sf /usr/bin/python3 /usr/bin/python \
    && rm -rf /var/lib/apt/lists/*

# root-cause: t_a929cfc3 -- venv из jammy несёт pip 22.0.2: он качает 820 MB torch wheel одним
# HTTP-ответом без докачки, и обрыв egress ПК ("TimeoutError: The read operation timed out",
# runs 39927449738/39927930315/39928140500/39928382766) валил весь слой. Докачка Range включена
# по умолчанию с pip 25.2; 26.2 падает на смещённом Range вместо порчи файла (#14131).
# Пин pip + RESUME_RETRIES; гард: pipeline/test_ace_dockerfile_pins.py.
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir "pip==26.2.2"
ENV PATH="/opt/venv/bin:$PATH" \
    PIP_RESUME_RETRIES=20

WORKDIR /app
# Пин к известному апстрим-коммиту (последний main на 2026-10)
RUN git clone https://github.com/ace-step/ACE-Step.git /tmp/ace \
 && git -C /tmp/ace checkout 1bee4c9f5b43e30995f8d4d33b3919197ce1bd68 \
 && cp -a /tmp/ace/. /app/ \
 && rm -rf /tmp/ace/.git /tmp/ace

# torch-тройка СТРОГО из cu128-индекса; bare `torch` в requirements.txt
# после этого считается уже удовлетворённым
# ponytail: gradio пин — код ACE-Step (фев 2026) несовместим с gradio 6.x
# (gr.Audio(show_download_button=...) упал в ACE-Step/acestep/ui/components.py);
# пин 5.x, поднять при обновлении апстрима.
# root-cause: t_a929cfc3 -- тройка запинена: без пина индекс мог дать несовместимый набор при релизе.
RUN pip install --no-cache-dir "torch==2.11.0" "torchvision==0.26.0" "torchaudio==2.11.0" \
      --index-url https://download.pytorch.org/whl/cu128 \
 && pip install --no-cache-dir "gradio==5.23.0" \
 && pip install --no-cache-dir "torchcodec==0.11.1" --index-url https://download.pytorch.org/whl/cu128 \
 && pip install --no-cache-dir hf_transfer \
 && pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir .

RUN useradd -m -u 1001 appuser \
 && mkdir -p /app/outputs /app/checkpoints /app/logs \
 && chown -R appuser:appuser /app
USER appuser

EXPOSE 7865
VOLUME ["/app/checkpoints", "/app/outputs", "/app/logs"]

# start-period большой: первый старт качает чекпоинт (~8 GB) из HF
HEALTHCHECK --interval=30s --timeout=5s --start-period=600s --retries=10 \
  CMD curl -sf http://localhost:7865/ >/dev/null || exit 1

CMD ["python", "acestep/gui.py", "--server_name", "0.0.0.0", "--bf16", "true"]
