"""Compare skill classifiers on a labelled CSV.

    python -m skills_lab evaluate                                    # the bundled synthetic sample (offline backends)
    python -m skills_lab evaluate --backends all                     # also try the Hugging Face backends
    python -m skills_lab evaluate --data my_entries.csv --cv 5       # YOUR confirmed entries, 5-fold cross-validation

CSV columns:  text, labels (category keys joined by ';')   optional: split (seed/test/blind...), kind, id
Trained backends learn from rows with split == 'seed' and are scored on every other split; if the file has no 'seed'
rows (or you pass --cv N) every backend is scored with N-fold cross-validation instead.
Metrics:  top-1 = the best-scoring category is one of the true labels (needs no threshold, the fairest single number);
          micro-F1 = precision/recall of ALL categories attached at the backend's default threshold.
"""
from __future__ import annotations

import csv
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from .backends import ALL_BACKENDS, Backend, BackendUnavailable, get_backend
from .taxonomy import KEYS

DEFAULT_DATA = Path(__file__).parent / "data" / "sample_entries.csv"


def load_csv(path: str | Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["gold"] = [x.strip() for x in (r.get("labels") or "").split(";") if x.strip()]
        bad = [g for g in r["gold"] if g not in KEYS]
        if bad:
            raise ValueError(f"unknown category {bad} in row {r.get('id') or r['text'][:40]!r}; valid: {', '.join(KEYS)}")
        r.setdefault("split", "")
        r["kind"] = r.get("kind") or "-"
    return [r for r in rows if r["gold"]]


def metrics(preds: list[list[tuple[str, float]]], rows: list[dict]) -> dict:
    tp = fp = fn = 0
    hit = 0
    per = defaultdict(lambda: [0, 0, 0])  # key -> tp, fp, fn
    by_kind: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for p, r in zip(preds, rows):
        gold, got = set(r["gold"]), {k for k, _ in p}
        ok = bool(p) and p[0][0] in gold
        hit += ok
        by_kind[r["kind"]][0] += ok
        by_kind[r["kind"]][1] += 1
        tp += len(gold & got); fp += len(got - gold); fn += len(gold - got)
        for k in KEYS:
            per[k][0] += k in gold and k in got
            per[k][1] += k not in gold and k in got
            per[k][2] += k in gold and k not in got
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    cat = {}
    for k, (a, b, c) in per.items():
        p_ = a / (a + b) if a + b else 0.0
        r_ = a / (a + c) if a + c else 0.0
        cat[k] = {"precision": p_, "recall": r_, "f1": 2 * p_ * r_ / (p_ + r_) if p_ + r_ else 0.0, "support": a + c}
    return {"top1": hit / len(rows), "precision": prec, "recall": rec, "micro_f1": f1, "n": len(rows),
            "by_kind": {k: v[0] / v[1] for k, v in by_kind.items()}, "per_category": cat}


def _fit_predict(backend: Backend, train: list[dict], test: list[dict]):
    if backend.needs_training:
        backend.fit([r["text"] for r in train], [r["gold"] for r in train])
    return backend.predict([r["text"] for r in test])


def evaluate_backend(backend: Backend, rows: list[dict], cv: int = 0) -> dict:
    t0 = time.time()
    seed = [r for r in rows if r["split"] == "seed"]
    if cv or not seed:
        folds = max(2, cv or 5)
        idx = np.random.RandomState(0).permutation(len(rows))
        preds: list = [None] * len(rows)
        for f in range(folds):
            te = idx[f::folds]
            tr = [rows[i] for i in idx if i not in set(te)]
            for i, p in zip(te, _fit_predict(backend, tr, [rows[i] for i in te])):
                preds[i] = p
        scored, scored_preds = rows, preds
        how = f"{folds}-fold cross-validation"
    else:
        scored = [r for r in rows if r["split"] != "seed"]
        scored_preds = _fit_predict(backend, seed, scored)
        how = f"trained on {len(seed)} seed rows" if backend.needs_training else "no training"
    out = metrics(scored_preds, scored)
    out["how"] = how
    out["seconds"] = time.time() - t0
    out["by_split"] = {}
    for sp in sorted({r["split"] for r in scored if r["split"]}):
        sub = [(p, r) for p, r in zip(scored_preds, scored) if r["split"] == sp]
        out["by_split"][sp] = metrics([p for p, _ in sub], [r for _, r in sub])["top1"]
    return out


def run(data: str | Path | None = None, backends: list[str] | None = None, cv: int = 0, per_category: bool = False,
        model: str | None = None) -> dict[str, dict]:
    rows = load_csv(data or DEFAULT_DATA)
    names = list(ALL_BACKENDS) if backends == ["all"] else (backends or ["keyword", "tfidf"])
    counts = Counter(k for r in rows for k in r["gold"])
    print(f"{len(rows)} labelled entries; entries per category: " + ", ".join(f"{k}={counts[k]}" for k in KEYS))
    results: dict[str, dict] = {}
    for name in names:
        try:
            kw = {"model_name": model} if model and name in ("embed_zeroshot", "embed_logreg", "nli_zeroshot") else {}
            backend = get_backend(name, **kw)
        except BackendUnavailable as exc:
            print(f"\n{name}: SKIPPED ({exc})")
            continue
        res = evaluate_backend(backend, rows, cv)
        results[name] = res
    if results:
        print(f"\n{'backend':16s} {'top-1':>6s} {'micro-F1':>9s} {'precision':>10s} {'recall':>7s} {'sec':>6s}   how")
        for name, r in results.items():
            print(f"{name:16s} {r['top1']:6.0%} {r['micro_f1']:9.2f} {r['precision']:10.2f} {r['recall']:7.2f} {r['seconds']:6.1f}   {r['how']}")
        print("\ntop-1 by split / kind:")
        for name, r in results.items():
            print(f"  {name:16s} " + "  ".join(f"{k}={v:.0%}" for k, v in {**r['by_split'], **{'kind:' + k: v for k, v in r['by_kind'].items() if k != '-'}}.items()))
        if per_category:
            for name, r in results.items():
                print(f"\n{name}: per-category F1 (support)")
                print("  " + "  ".join(f"{k}={c['f1']:.2f}({c['support']})" for k, c in r["per_category"].items()))
    return results
