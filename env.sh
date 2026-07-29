# Ollama configuration for a 16 GB fanless M4 Air (PLAN.md §4 Phase 0.2).
#   source ./env.sh
#
# These must be set for the SERVER process, not the client. If Ollama is already
# running, restart it after sourcing, or the settings are ignored:
#   pkill ollama && ollama serve

# Keep the 12B resident. Reloading 7.6 GB between phases dominates wall clock.
export OLLAMA_KEEP_ALIVE=-1

# One model: gemma4:12b (7.6 GB). The cap is kept above 1 anyway, because
# the failure below is about what gets loaded ALONGSIDE it.
#
# WARNING: this cap does NOT protect the memory budget. `gemma4:e4b` is 9.6 GB;
# if anything requests it, Ollama will happily load it ALONGSIDE the 12B and
# push a 16 GB machine into swap. The only real protection is never requesting
# it. Consider `ollama rm gemma4:e4b`.
export OLLAMA_MAX_LOADED_MODELS=2

# Flash attention is a prerequisite for KV cache quantization below.
export OLLAMA_FLASH_ATTENTION=1

# q8_0 KV cache: roughly halves cache memory versus f16. Gemma uses sliding-window
# attention and support has historically been uneven — Phase 0 verification #3
# confirms this actually engages rather than silently no-opping. If it does not,
# the <=3 GB cache budget in PLAN.md's constraint table is wrong.
export OLLAMA_KV_CACHE_TYPE=q8_0

# --- harness ---------------------------------------------------------------
export NANOLOOP_BACKEND=ollama          # ollama | litert | aistudio
# GEMMA 4 ONLY. All three backends serve Gemma 4; `check_model()` in
# model_ollama.py refuses anything else, including via NANOLOOP_MODEL. No Gemini
# model is used anywhere in this repo.
#
# aistudio = gemma-4-26b-a4b-it via Google AI Studio, used as a measurement
# ORACLE (eval --oracle), not as a development runtime. The endpoint is Google's;
# the model on it is Gemma. Key goes in .env (gitignored) as GEMINI_API_KEY=...
# — that is AI Studio's credential name, not a model choice. Never in this file.
export NANOLOOP_STRUCTURED_MODE=openai  # /v1 only; native /api/chat uses `format`
# Reasoning OFF. Gemma 4 is a reasoning model and leaving it on measured 8x
# slower (222s vs 27s on the same prompt). Only /api/chat honours this.
export NANOLOOP_THINK=0
export NANOLOOP_CALLLOG=./calls.jsonl
export NANOLOOP_N_CANDIDATES=2          # PLAN.md D7 — do not raise to fix quality
export NANOLOOP_FUZZY=0                 # measure EXACT anchor-hit first (Phase 2)

echo "ollama: keep_alive=$OLLAMA_KEEP_ALIVE max_loaded=$OLLAMA_MAX_LOADED_MODELS \
flash_attn=$OLLAMA_FLASH_ATTENTION kv=$OLLAMA_KV_CACHE_TYPE"
echo "harness: backend=$NANOLOOP_BACKEND structured=$NANOLOOP_STRUCTURED_MODE \
n_candidates=$NANOLOOP_N_CANDIDATES fuzzy=$NANOLOOP_FUZZY"
