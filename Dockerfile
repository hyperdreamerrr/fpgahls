# Build on the official base image. It carries ROCm, the Vitis HLS toolchain and
# a working inference stack for the target architecture; rebuilding that yourself
# is a large amount of work for no score.
#
# The base image targets gfx1100 (Radeon PRO W7900), which both the preliminary
# round and the finals run on. There is no gfx1201 variant to pin.
#
# ★ The tag below is a PLACEHOLDER. The real image name is announced before
#   the validation window; until then this build only works if you pass the
#   name explicitly:
#
#     docker build --build-arg BASE_IMAGE=<announced name> -t myteam-agent .
#
ARG BASE_IMAGE=fpgachina2026/base-gfx1100:REPLACE_WITH_ANNOUNCED_TAG
FROM ${BASE_IMAGE}

# --- everything must be baked in: the sandbox has no network ----------------

WORKDIR /opt/agent

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY agent/  agent/
COPY skill/  skill/
COPY serve/  serve/
COPY model/  model/
COPY run.sh run_baseline.sh manifest.json REPORT.md ./
RUN chmod +x run.sh run_baseline.sh serve/start.sh serve/llamacpp.sh

# Defensive. A stale __pycache__ dragged in from a development checkout carries
# absolute host paths and source mtimes inside the .pyc bytes, so it would both
# break the hash freeze and leak the author's directory layout.
RUN find . -name __pycache__ -type d -prune -exec rm -rf {} +

# Model weights. Copy them in, or bind-mount at run time -- but they must be on
# local disk before the network goes away. `huggingface-cli download` at startup
# fails in the sandbox.
#
# COPY models/ /models/

# LLM_MODEL and MODEL_NAME must be the SAME name. agent/llm.py reads LLM_MODEL;
# baseline.py reads MODEL_NAME (and falls back to the first entry of
# /v1/models). If they diverge, the numerator and denominator silently run two
# different names and the gain is meaningless. The service alias in
# serve/llamacpp.sh must match both.
#
# AGENT_TMP/EDA_TMP/SELFTEST_TMP point at /var/tmp, not /tmp: on Radeon Cloud
# /tmp is a 4 GB RAM disk, and a synthesis scratch tree does not fit there
# (FAQ Q5, API_CONTRACT section 9). /var/tmp is on the container filesystem.
ENV LLM_BACKEND=openai \
    LLM_BASE_URL=http://localhost:8000/v1 \
    LLM_MODEL=nemotron-3.5-lightning-c512k \
    MODEL_NAME=nemotron-3.5-lightning-c512k \
    LLM_API_KEY=dummy \
    AGENT_TMP=/var/tmp \
    EDA_TMP=/var/tmp/eda \
    SELFTEST_TMP=/var/tmp \
    HLS_PART=xczu3eg-sbva484-1-e \
    HLS_PERIOD_NS=5 \
    PYTHONDONTWRITEBYTECODE=1

# PYTHONDONTWRITEBYTECODE: the submitted package is hash-frozen, and .pyc bytes
# are not reproducible (see above). run.sh is carried **byte-identical to the
# official example** -- it is the entry-point contract, not ours to edit -- so
# bytecode suppression has to be set from the environment instead.

# Do NOT set PATH for the toolchain here. The base image already exports it,
# along with XILINX_VITIS / XILINX_VIVADO, and the install layout differs by
# release. Read the variables instead of hardcoding a path. The judge needs `v++`
# on PATH for the L4 synthesis level; the toolchain we measured on during
# development is Vitis HLS 2025.2 (Build 6295257) -- see REPORT.md section 6.

# Container metadata only. On Radeon Cloud both services bind 127.0.0.1 and just
# 7860 is published, via rc-tunnel. See serve/README.md.
EXPOSE 7860 8000

# Not an entrypoint on purpose. Evaluation is by HTTP submission: serve/start.sh
# brings up the resident inference service, then serve/serve_api.py is started.
# In the container-rebuild fallback the organisers run serve/start.sh once and
# then call run.sh / run_baseline.sh per task directly.
CMD ["/bin/bash"]
