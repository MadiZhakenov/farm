#!/bin/bash
# Kimodo text-to-motion helpers (Git Bash).
#   bash lowpoly/kimodo.sh server            # keep Llama text encoder in RAM (port 9550, localhost only)
#   bash lowpoly/kimodo.sh gen "prompt" OUT_STEM [duration] [seed]   # -> OUT_STEM.npz + OUT_STEM.bvh
# Text encoder = open copy of Llama 3 8B Instruct in tools/kimodo/text_encoders (no Meta approval needed),
# runs on CPU (8 GB GPU is too small); the motion model itself runs on the GPU.
FARM="$(cd "$(dirname "$0")/.." && pwd)"
K="$FARM/tools/kimodo"
export TEXT_ENCODERS_DIR="$K/text_encoders"
export TEXT_ENCODER_DEVICE=cpu
export HF_HUB_OFFLINE=1
export PYTHONIOENCODING=utf-8
export GRADIO_SERVER_NAME=127.0.0.1
export GRADIO_ANALYTICS_ENABLED=False
# gradio only serves files from the system temp dir or cwd
export TEXT_ENCODER_TMP_FOLDER="${TEMP:-/tmp}/kimodo_te"
mkdir -p "$TEXT_ENCODER_TMP_FOLDER"

case "$1" in
  server)
    cd "$K" && exec venv/Scripts/kimodo_textencoder.exe
    ;;
  gen)
    PROMPT="$2"; OUT="$3"; DUR="${4:-5}"; SEED="${5:-1}"
    cd "$K" && venv/Scripts/kimodo_gen.exe "$PROMPT" --duration "$DUR" --seed "$SEED" \
      --bvh --bvh_standard_tpose --output "$OUT"
    ;;
  *)
    echo "usage: $0 server | gen \"prompt\" OUT_STEM [duration] [seed]"; exit 1
    ;;
esac
