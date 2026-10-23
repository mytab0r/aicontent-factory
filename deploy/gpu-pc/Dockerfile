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

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

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
# root-cause: t_43dc0241 -- 820MB torch wheel качается pip'ом за один HTTP-ответ;
# транспорт-обрыв egress ПК (то же семейство, что t_0a4cae59 к ghcr/CloudFront) даёт
# "Read timed out" и весь RUN падает без докачки. Механика класса: качаем wheels
# отдельно curl'ом с Range-докачкой (4 попытки, -C -), затем pip ставит из локальных
# файлов -- сеть больше не входит в слой.
RUN mkdir -p /tmp/wheels \
 && for u in \
      "https://download.pytorch.org/whl/cu128/torch-2.11.0%2Bcu128-cp310-cp310-manylinux_2_28_x86_64.whl" \
      "https://download.pytorch.org/whl/cu128/torchvision-0.26.0%2Bcu128-cp310-cp310-manylinux_2_28_x86_64.whl" \
      "https://download.pytorch.org/whl/cu128/torchaudio-2.11.0%2Bcu128-cp310-cp310-manylinux_2_28_x86_64.whl" \
    ; do f="/tmp/wheels/$(basename "$u" | sed 's/%2B/+/')"; \
      for n in 1 2 3 4; do curl -fSL --retry 5 --retry-delay 5 --retry-all-errors -C - -o "$f" "$u" && break; [ $n = 4 ] && exit 1; sleep $((n*10)); done; \
    done \
 && pip install --no-cache-dir /tmp/wheels/*.whl \
 && rm -rf /tmp/wheels \
 && pip install --no-cache-dir "gradio==5.23.0" \
 && pip install --no-cache-dir torchcodec --index-url https://download.pytorch.org/whl/cu128 \
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
