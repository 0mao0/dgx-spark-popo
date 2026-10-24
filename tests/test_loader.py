# -*- coding: utf-8 -*-
"""loader 单测：CI 无真实清单，用夹具验证加载、校验与取样的确定性。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "frozen"))
import loader  # noqa: E402


def make_manifest(tmp_path, mutate=None):
    docs = [
        {"doc_id": "doc-b", "library": "L", "sha256": "0" * 64,
         "size_bytes": 100, "pages": 1, "stratum": "single_page"},
        {"doc_id": "doc-a", "library": "L", "sha256": "0" * 64,
         "size_bytes": 100, "pages": 30, "stratum": "table_dense"},
        {"doc_id": "doc-c", "library": "L", "sha256": "0" * 64,
         "size_bytes": 100, "pages": 250, "stratum": "long"},
        {"doc_id": "doc-d", "library": "L", "sha256": "0" * 64,
         "size_bytes": 100, "pages": 12, "stratum": "regular"},
    ]
    if mutate:
        mutate(docs)
    m = {"version": "frozen-v1", "seed": 1, "thresholds": {},
         "excluded_over_size": 0, "docs": docs}
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(m), encoding="utf-8")
    return m


def test_load_none_without_env(tmp_path, monkeypatch):
    monkeypatch.delenv("POPO_FROZEN_MANIFEST", raising=False)
    assert loader.load_manifest() is None


def test_load_and_validate(tmp_path):
    m = make_manifest(tmp_path)
    got = loader.load_manifest(str(tmp_path / "manifest.json"))
    assert got["version"] == "frozen-v1"
    assert len(got["docs"]) == 4


def test_bad_stratum_rejected(tmp_path):
    make_manifest(tmp_path, mutate=lambda docs: docs[0].update(stratum="nope"))
    try:
        loader.load_manifest(str(tmp_path / "manifest.json"))
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_missing_key_rejected(tmp_path):
    make_manifest(tmp_path, mutate=lambda docs: docs[1].pop("sha256"))
    try:
        loader.load_manifest(str(tmp_path / "manifest.json"))
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_pick_deterministic(tmp_path):
    m = make_manifest(tmp_path)
    a = loader.pick(m, 2)
    b = loader.pick(m, 2)
    assert [d["doc_id"] for d in a] == [d["doc_id"] for d in b] == ["doc-b", "doc-a"]


def test_pick_differential_strata_round_robin(tmp_path):
    m = make_manifest(tmp_path)
    picked = loader.pick_differential(m, n_multi=3, n_single=1)
    ids = [d["doc_id"] for d in picked]
    assert ids[0] == "doc-b"                    # 单页优先，走放宽判据
    assert set(ids[1:]) == {"doc-a", "doc-c", "doc-d"}  # 多页轮转覆盖各层


def test_doc_dir(tmp_path):
    m = make_manifest(tmp_path)
    d = loader.doc_dir(m["docs"][0], "/corpora")
    assert str(d).replace("\\", "/").endswith("L/documents/doc-b")
