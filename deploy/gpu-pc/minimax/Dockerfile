FROM nvidia/cuda:12.8.1-devel-ubuntu22.04
# Спайк t_737ca0ec: audio.cpp (форк fspecii, MiniMax Music 3) под RTX 5070 (sm_120).
# Один образ: тулчейн + бинарник. Веса НЕ в образе — named volume minimax-weights (disk_gate).
RUN mkdir -p /work /out && apt-get update && apt-get install -y --no-install-recommends git ca-certificates cmake g++ python3 && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/fspecii/audio.cpp-lowend-gpu /src \
 && cd /src && git checkout 3f593a39be053064cfe8cde0b13483c3deb920d6
RUN cmake -S /src -B /src/build \
      -DENGINE_ENABLE_CUDA=ON \
      -DCUDAToolkit_ROOT=/usr/local/cuda \
      -DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc \
      -DCMAKE_CUDA_ARCHITECTURES=120 \
      -DCMAKE_BUILD_TYPE=Release \
 && cmake --build /src/build -j"$(nproc)"
ENV PATH=/src/build/bin:$PATH
