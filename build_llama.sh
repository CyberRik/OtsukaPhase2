#!/bin/bash
export PATH="/usr/local/cuda/bin:$PATH"
cd /home/team-a/Desktop/toolcallLM/qwen3/llama.cpp
cmake -B build -DGGML_CUDA=ON
cmake --build build --config Release -j 32
