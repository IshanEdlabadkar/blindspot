#!/usr/bin/env bash
# Print a Python interpreter that has the given modules (default: what the app needs).
# Homebrew can repoint python3 at a bare install, so we check instead of trusting python3.
#   ./scripts/find_python.sh                       -> app modules
#   ./scripts/find_python.sh sentence_transformers -> also needs that
need="streamlit, numpy, requests${1:+, $1}"
for cand in "${PYTHON:-}" python3.12 /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
            /opt/homebrew/opt/python@3.12/bin/python3.12 python3 python; do
  [ -n "$cand" ] || continue
  if "$cand" -c "import $need" >/dev/null 2>&1; then echo "$cand"; exit 0; fi
done
echo "ERROR: no Python found with: $need" >&2
echo "Fix:   python3.12 -m pip install streamlit numpy requests sentence-transformers" >&2
exit 1
