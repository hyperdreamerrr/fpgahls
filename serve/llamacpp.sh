#!/usr/bin/env bash
# Start the local inference service -- llama.cpp backend.
#
# This is the declared serving stack (manifest.json -> serving.backend).
# It replaces serve/vllm.sh: the platform image's vLLM 0.27.1 has no GGUF
# loader, so the vLLM path exits before loading the model (RUNLOG 续记 2,
# results/amd-bringup-20261019/).
#
# Measured on the AMD Radeon Cloud instance
#   image radeon-cloud-global/fpgachina-rtlhls@sha256:a7cf627e1170
#   W7900D 48 GiB / gfx1100, ROCm 7.15.26333
#   llama-server 0.4.0-dev (build 1, commit f114f91)
#
#   ./serve/llamacpp.sh
#   export LLM_BACKEND=openai LLM_BASE_URL=http://127.0.0.1:8000/v1 LLM_MODEL=$SERVED_NAME
#
# Caliber values (do not change without updating model/MODEL.md and manifest):
#   MODEL, SERVED_NAME, MAX_LEN, NGL, the binary path.
# run_baseline.sh has to run against exactly this service.
#
# NOTE --jinja. docs/FAQ.md Q6 requires it: without it llama.cpp ignores the
# chat template's kwargs, so the thinking settings declared in manifest.json
# ("generation") would not take effect. The first cloud smoke run (59.85 tok/s,
# 26.59 GiB idle) predates this flag; it is recorded as a measured delta in
# results/pkg-sync-20261020/PREREG.md, not claimed as already measured.

set -euo pipefail

MODEL="${MODEL:-/models/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-UD-Q4_K_M.gguf}"  # local path, not a Hub id: the sandbox is offline
SERVED_NAME="${SERVED_NAME:-nemotron-3.5-lightning-c512k}"  # must equal LLM_MODEL / MODEL_NAME in serve/env.sh
PORT="${PORT:-8000}"
MAX_LEN="${MAX_LEN:-524288}"   # declared; measured effective value from /v1/models meta n_ctx
NGL="${NGL:-999}"              # all layers on the single card (official FAQ Q6 value)
# There is no llama.cpp equivalent of vLLM's --gpu-memory-utilization. The
# measured footprint is what it is; do not invent a percentage here.

BIN="${LLAMACPP_BIN:-/opt/llamacpp/llama-server}"

# The image splits rocBLAS' kernel libraries away from librocblas.so.5: the .so
# lives under _rocm_sdk_devel/lib, but the per-arch Tensile kernels live under
# _rocm_sdk_libraries/lib/rocblas/library. Without this variable the first HIP
# kernel launch dies with
#   rocBLAS error: Cannot read .../rocblas/library/TensileLibrary.dat ... gfx1100
#
# Prefer an inherited value, then the officially documented path
# (/opt/llamacpp/rocblas/library, FAQ Q6), then the path measured on this image,
# then a filesystem search before giving up. An empty value is not fatal: some
# builds ship a monolithic rocBLAS and need no override.
if [[ -z "${ROCBLAS_TENSILE_LIBPATH:-}" ]]; then
    for cand in \
        "/opt/llamacpp/rocblas/library" \
        "/opt/python/lib/python3.14/site-packages/_rocm_sdk_libraries/lib/rocblas/library"
    do
        if [[ -d "$cand" ]]; then
            ROCBLAS_TENSILE_LIBPATH="$cand"
            break
        fi
    done
    if [[ -z "${ROCBLAS_TENSILE_LIBPATH:-}" ]]; then
        found="$(find /opt -maxdepth 10 -type d -path '*rocblas/library' -print -quit 2>/dev/null || true)"
        [[ -n "$found" ]] && ROCBLAS_TENSILE_LIBPATH="$found"
    fi
fi
export ROCBLAS_TENSILE_LIBPATH="${ROCBLAS_TENSILE_LIBPATH:-}"

# Single card. Tensor/pipeline parallelism across cards is not usable here,
# and the memory budget is per-card anyway.
export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"

if [[ ! -x "$BIN" ]]; then
    echo "llama-server not found or not executable: $BIN" >&2
    echo "set LLAMACPP_BIN to its real path" >&2
    exit 127
fi
if [[ ! -r "$MODEL" ]]; then
    echo "model file not readable: $MODEL" >&2
    exit 66
fi
if [[ -z "$ROCBLAS_TENSILE_LIBPATH" || ! -d "$ROCBLAS_TENSILE_LIBPATH" ]]; then
    echo "warning: rocBLAS Tensile library path not found; if the first request dies" >&2
    echo "         with 'Cannot read ... TensileLibrary.dat', set ROCBLAS_TENSILE_LIBPATH" >&2
fi

# -np is deliberately left at the build default. Whether evaluation should pin
# it to 1 is an open caliber question; do not set it here without a
# pre-registration.
exec "$BIN" \
    -m "$MODEL" \
    -c "$MAX_LEN" \
    -ngl "$NGL" \
    --alias "$SERVED_NAME" \
    --host 127.0.0.1 \
    --port "$PORT" \
    --jinja \
    --no-webui
