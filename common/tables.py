"""Load and verify the artifacts/ tables (docs/contracts.md sections 1, 3, 8)."""
import hashlib
import json
from pathlib import Path

import numpy as np

from common.embedding import ARTIFACTS
from common.records import RECORD_BYTES, unpack_record


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_artifacts(artifacts_dir=ARTIFACTS):
    d = Path(artifacts_dir)
    m = json.loads((d / "manifest.json").read_text())
    n, dim, size = m["num_chunks"], m["embedding"]["dim"], m["pir"]["record_bytes"]
    table = np.fromfile(d / "score_table.bin", dtype=np.int8)
    if table.size != n * dim:
        raise ValueError(f"score table has {table.size} values; expected {n * dim}")
    store = (d / "fetch_store.bin").read_bytes()
    if len(store) != n * size:
        raise ValueError(f"fetch store has {len(store)} bytes; expected {n * size}")
    return m, table.reshape(n, dim), store


def get_record(store: bytes, i: int) -> dict:
    return unpack_record(store[i * RECORD_BYTES:(i + 1) * RECORD_BYTES])


def verify_hashes(manifest: dict, artifacts_dir=ARTIFACTS) -> None:
    d = Path(artifacts_dir)
    for key, name in (("score_table", "score_table.bin"), ("fetch_store", "fetch_store.bin")):
        if sha256_file(d / name) != manifest["hashes"][key]:
            raise ValueError(f"{name} does not match the manifest hash")
