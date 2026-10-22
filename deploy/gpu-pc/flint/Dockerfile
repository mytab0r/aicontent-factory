# t_2ca44c81: llama.cpp b11803 (первый релиз с Flint, PR 30928) cu12.8, sm_120a в бинарях.
# ponytail: официального server-cuda с Flint ещё нет (последний b11783) — когда выйдет, заменить на ghcr.io/ggml-org/llama.cpp:server-cuda.
FROM nvidia/cuda:12.8.1-runtime-ubuntu24.04
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libssl3 curl ca-certificates && rm -rf /var/lib/apt/lists/*
ADD llama-b11803-bin-ubuntu-cuda-12.8-x64.tar.gz /opt/
ENV LD_LIBRARY_PATH=/opt/llama-b11803
ENTRYPOINT ["/opt/llama-b11803/llama-server"]
