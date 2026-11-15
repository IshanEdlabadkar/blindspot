# Sourced by the demo scripts: no telemetry, and no network calls for models once they're downloaded.
# (The question never goes to these services anyway; this stops the app from announcing itself or
# phoning home on every start.)
export HF_HUB_DISABLE_TELEMETRY=1 DO_NOT_TRACK=1
hub="${HF_HUB_CACHE:-${HF_HOME:-$HOME/.cache/huggingface}/hub}"
if [ -d "$hub/models--BAAI--bge-small-en-v1.5" ] && [ -d "$hub/models--cross-encoder--ms-marco-MiniLM-L6-v2" ]; then
  export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1   # both models are on disk: load them without asking the Hub
fi
