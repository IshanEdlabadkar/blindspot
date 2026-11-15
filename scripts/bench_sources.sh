#!/usr/bin/env bash
# Compare source-selection settings for the answer step (how many passages reach the model, and how
# many different pages and servers the answers draw on), with real answers, on the same questions.
#
#   make bench-sources                       # 40 questions, five settings, ~40 min with Llama on CPU
#   make bench-sources ARGS="--limit 96"     # every question (~2 h)
#
# Model outputs are cached by exact prompt, so a setting that picks the same sources as an earlier
# one costs no model time. Needs make demo (or the helper + servers + Ollama) running.
set -euo pipefail
cd "$(dirname "$0")/.."
ARGS=${ARGS:-"--limit 40"}
STAMP=$(date +%Y%m%d-%H%M%S)
CACHE=eval/results/bench/llm_cache.jsonl
curl -fsS -o /dev/null --max-time 2 http://127.0.0.1:8090/health 2>/dev/null || {
  echo "starting the key helper"; mkdir -p data; (cd crypto-server && go build -o crypto-helper ./cmd/crypto-helper)
  nohup ./crypto-server/crypto-helper > data/helper.out 2>&1 & sleep 2; }
runs=()
for cfg in "" "min=2" "pages=1,min=2" "pages=1,min=3,margin=7" "pages=1,n=8,margin=7,min=3"; do
  name="$STAMP-sources-${cfg:-default}"; name=${name//[=,]/-}
  echo; echo "=== source setting: ${cfg:-default (current)} ==="
  python3 -m eval.bench --answer real --sources "$cfg" --llm-cache "$CACHE" --name "$name" $ARGS | grep -E '^ +[^ ]+ r0 ' || true
  python3 - "$name" <<'PY'
import json, sys
s = json.load(open(f"eval/results/bench/{sys.argv[1]}/summary.json"))
a, y = s["accuracy"], s["synthesis"] or {}
f = lambda x: f"{x['n']}/{x['of']}" if x and x.get("of") else "n/a"
print(f"  answered {f(a.get('answerable_answered'))}, cited right page {f(a.get('answerable_cited_right_page'))}, "
      f"wrong answers {f(a.get('wrong_answers'))}, sources/answer {y.get('sources_to_model', {}).get('mean', 'n/a')}, "
      f"2+ pages cited {f(y.get('answers_citing_2plus_pages'))}; model cache {s['meta'].get('llm_cache')}")
PY
  runs+=("eval/results/bench/$name")
done
echo; echo "=== comparison ==="
python3 -m eval.bench --compare "${runs[@]}"
