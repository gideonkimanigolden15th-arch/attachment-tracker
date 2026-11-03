"""Skill classifiers behind one interface:  backend.scores(texts) -> array (n_texts, n_categories) in [0, 1].

Offline (work anywhere, tested):
    keyword            hand-written word lists from taxonomy.py + spelling-tolerant matching (survives OCR typos)
    tfidf              character n-gram TF-IDF + logistic regression, trained on labelled entries (also OCR-typo tolerant)

Hugging Face (need `pip install sentence-transformers` / `transformers torch` and a one-time model download;
the code paths are tested with stand-in models, but NOT with real weights, because this was built on a machine
that cannot reach huggingface.co - run `python -m skills_lab evaluate` on your PC to measure them):
    embed_zeroshot     sentence-transformers: cosine similarity between the entry and each category description
    embed_logreg       sentence-transformers embeddings + logistic regression trained on labelled entries
    nli_zeroshot       an NLI model asked "is this text about <category>?" for every category
"""
from __future__ import annotations

import difflib
import math
import re
from typing import Callable, Sequence

import numpy as np

from .taxonomy import BY_KEY, CATEGORIES, KEYS

_WORD = re.compile(r"[a-z0-9][a-z0-9+#./'-]*")


class BackendUnavailable(RuntimeError):
    """A backend needs a package or model that is not installed on this computer."""


def decide(row: np.ndarray, threshold: float, max_labels: int = 3, relative: float = 0.6, floor: float = 0.15
           ) -> list[tuple[str, float]]:
    """Turn one row of scores into (category, score) picks, best first. Empty list = 'cannot tell'."""
    order = np.argsort(-row)
    top = float(row[order[0]])
    if top < floor:
        return []
    picks = [int(i) for i in order[:max_labels] if row[i] >= threshold and row[i] >= relative * top]
    return [(KEYS[i], float(row[i])) for i in (picks or [int(order[0])])]


class Backend:
    name = "base"
    needs_training = False
    threshold = 0.5      # score at which a category is attached to an entry
    floor = 0.15         # below this best score the entry is left unclassified

    def fit(self, texts: Sequence[str], labels: Sequence[Sequence[str]]) -> "Backend":
        return self

    def scores(self, texts: Sequence[str]) -> np.ndarray:  # pragma: no cover - interface
        raise NotImplementedError

    def predict(self, texts: Sequence[str], threshold: float | None = None, max_labels: int = 3
                ) -> list[list[tuple[str, float]]]:
        s = self.scores(texts)
        t = self.threshold if threshold is None else threshold
        return [decide(row, t, max_labels, floor=self.floor) for row in s]


def _binarize(labels: Sequence[Sequence[str]]) -> np.ndarray:
    y = np.zeros((len(labels), len(KEYS)), dtype=int)
    for i, ls in enumerate(labels):
        for k in ls:
            y[i, KEYS.index(k)] = 1
    return y


# ================================================================== keyword
class KeywordBackend(Backend):
    """Counts keyword hits per category. Explainable, instant, no download, tolerant of typos."""

    name = "keyword"
    threshold = 0.5
    fuzzy_cutoff = 0.8

    def __init__(self) -> None:
        self._pat: dict[str, list[tuple[re.Pattern, str, float]]] = {}
        self._single: dict[str, list[tuple[str, float]]] = {}
        for c in CATEGORIES:
            pats = []
            for kw, w in c.keywords.items():
                pats.append((re.compile(r"(?<![a-z0-9])" + re.escape(kw) + r"(?:s|es|ed|d|ing)?(?![a-z0-9])"), kw, w))
                if " " not in kw and len(kw) >= 5 and kw.isalpha():
                    self._single.setdefault(kw, []).append((c.key, w))
            self._pat[c.key] = pats
        self._vocab = sorted(self._single)

    def hits(self, text: str) -> dict[str, list[tuple[str, float]]]:
        t = text.lower()
        found: dict[str, list[tuple[str, float]]] = {c.key: [] for c in CATEGORIES}
        exact: set[str] = set()
        for key, pats in self._pat.items():
            for rx, kw, w in pats:
                if rx.search(t):
                    found[key].append((kw, w))
                    exact.add(kw)
        known = {w for ws in found.values() for w, _ in ws}
        for tok in _WORD.findall(t):
            tok = tok.strip(".'-")
            if len(tok) < 5 or not tok.isalpha() or tok in self._single or tok in known:
                continue
            m = difflib.get_close_matches(tok, self._vocab, n=1, cutoff=self.fuzzy_cutoff)
            if m:  # looks like a misspelt keyword (typical OCR error): count it a little less than an exact hit
                for key, w in self._single[m[0]]:
                    if all(k != m[0] for k, _ in found[key]):
                        found[key].append((f"{m[0]}~{tok}", 0.8 * w))
        return found

    def scores(self, texts: Sequence[str]) -> np.ndarray:
        out = np.zeros((len(texts), len(KEYS)))
        for i, text in enumerate(texts):
            h = self.hits(text)
            for j, k in enumerate(KEYS):
                out[i, j] = 1 - math.exp(-0.9 * sum(w for _, w in h[k]))
        return out

    def explain(self, text: str) -> dict[str, list[str]]:
        """Which words made each category fire (for showing the student/supervisor why)."""
        return {k: [w for w, _ in v] for k, v in self.hits(text).items() if v}


# ==================================================================== tfidf
class TfidfBackend(Backend):
    """Character n-grams + logistic regression. Learns from labelled entries; robust to spelling noise."""

    name = "tfidf"
    needs_training = True
    threshold = 0.35

    def __init__(self) -> None:
        self._model = None

    def fit(self, texts, labels) -> "TfidfBackend":
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.multiclass import OneVsRestClassifier
        from sklearn.pipeline import make_pipeline

        y = _binarize(labels)
        self._cols = [j for j in range(len(KEYS)) if y[:, j].any()]  # classes with at least one example
        self._model = make_pipeline(
            TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True, lowercase=True),
            OneVsRestClassifier(LogisticRegression(C=20, max_iter=2000, class_weight="balanced")),
        ).fit(list(texts), y[:, self._cols])
        return self

    def scores(self, texts) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("tfidf backend must be trained first (fit)")
        p = self._model.predict_proba(list(texts))
        out = np.zeros((len(texts), len(KEYS)))
        out[:, self._cols] = p
        return out


# ================================================ Hugging Face: embeddings
class SentenceTransformerEncoder:
    """Wraps a sentence-transformers model. encode(list[str]) -> L2-normalised array."""

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2", device: str | None = None):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise BackendUnavailable("needs: pip install sentence-transformers") from exc
        self.model_name = model_name
        try:
            self.model = SentenceTransformer(model_name, device=device)
        except Exception as exc:  # no internet / unknown model name
            raise BackendUnavailable(f"could not load {model_name!r}: {exc}") from exc

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        return np.asarray(self.model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False))


def _unit(a: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(a, axis=1, keepdims=True)
    return a / np.where(n == 0, 1, n)


class EmbeddingZeroShotBackend(Backend):
    """No training: score = how close the entry's embedding is to each category's description."""

    name = "embed_zeroshot"
    threshold = 0.20
    floor = 0.12

    def __init__(self, encoder=None, model_name: str = "sentence-transformers/all-MiniLM-L6-v2", temperature: float = 0.05):
        self.encoder = encoder or SentenceTransformerEncoder(model_name)
        self.temperature = temperature
        desc = [f"{c.name}. {c.description}" for c in CATEGORIES]
        kws = [", ".join(list(c.keywords)[:25]) for c in CATEGORIES]
        self._proto = _unit(np.asarray(self.encoder.encode(desc)))
        self._proto_kw = _unit(np.asarray(self.encoder.encode(kws)))

    def scores(self, texts) -> np.ndarray:
        e = _unit(np.asarray(self.encoder.encode(list(texts))))
        sim = np.maximum(e @ self._proto.T, e @ self._proto_kw.T)
        z = sim / self.temperature
        z -= z.max(axis=1, keepdims=True)
        p = np.exp(z)
        return p / p.sum(axis=1, keepdims=True)


class EmbeddingLogRegBackend(Backend):
    """Embeddings from a pre-trained sentence model + a small classifier trained on your labelled entries.
    (This is the 'classifier head' half of SetFit; it needs far fewer examples than training a transformer.)"""

    name = "embed_logreg"
    needs_training = True
    threshold = 0.35

    def __init__(self, encoder=None, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        self.encoder = encoder or SentenceTransformerEncoder(model_name)
        self._clf = None

    def fit(self, texts, labels) -> "EmbeddingLogRegBackend":
        from sklearn.linear_model import LogisticRegression
        from sklearn.multiclass import OneVsRestClassifier

        y = _binarize(labels)
        self._cols = [j for j in range(len(KEYS)) if y[:, j].any()]
        self._clf = OneVsRestClassifier(LogisticRegression(C=10, max_iter=2000, class_weight="balanced")).fit(
            np.asarray(self.encoder.encode(list(texts))), y[:, self._cols])
        return self

    def scores(self, texts) -> np.ndarray:
        if self._clf is None:
            raise RuntimeError("embed_logreg backend must be trained first (fit)")
        p = self._clf.predict_proba(np.asarray(self.encoder.encode(list(texts))))
        out = np.zeros((len(texts), len(KEYS)))
        out[:, self._cols] = p
        return out


# ================================================ Hugging Face: NLI zero-shot
NLI_LABELS = {
    "networking": "computer networking, routers, switches, Wi-Fi and cabling",
    "troubleshooting": "troubleshooting and fixing computer problems or helping users with faults",
    "hardware": "computer hardware, devices, printers and equipment installation or repair",
    "os_admin": "operating systems and server administration such as Windows, Linux and user accounts",
    "security": "cybersecurity, antivirus, passwords and protecting data",
    "databases": "databases, SQL, spreadsheets and data entry",
    "software_web": "software development, programming and websites",
    "cloud": "cloud services, virtual machines, hosting and Microsoft 365",
    "docs_comms": "writing documentation, reports, presentations and training users",
    "professional": "workplace skills such as teamwork, customer care and time management",
}


class NliZeroShotBackend(Backend):
    """Asks an NLI model 'This work is about <category>' for each category (no training data needed, slowest)."""

    name = "nli_zeroshot"
    threshold = 0.5
    floor = 0.3

    def __init__(self, pipe: Callable | None = None, model_name: str = "facebook/bart-large-mnli"):
        if pipe is None:
            try:
                from transformers import pipeline
            except ImportError as exc:
                raise BackendUnavailable("needs: pip install transformers torch") from exc
            try:
                pipe = pipeline("zero-shot-classification", model=model_name)
            except Exception as exc:
                raise BackendUnavailable(f"could not load {model_name!r}: {exc}") from exc
        self.pipe = pipe
        self._labels = [NLI_LABELS[k] for k in KEYS]

    def scores(self, texts) -> np.ndarray:
        res = self.pipe(list(texts), candidate_labels=self._labels, hypothesis_template="This work is about {}.",
                        multi_label=True)
        if isinstance(res, dict):
            res = [res]
        out = np.zeros((len(texts), len(KEYS)))
        for i, r in enumerate(res):
            for lab, sc in zip(r["labels"], r["scores"]):
                out[i, self._labels.index(lab)] = sc
        return out


# ================================================================== registry
def get_backend(name: str, **kw) -> Backend:
    if name == "keyword":
        return KeywordBackend()
    if name == "tfidf":
        return TfidfBackend()
    if name == "embed_zeroshot":
        return EmbeddingZeroShotBackend(**kw)
    if name == "embed_logreg":
        return EmbeddingLogRegBackend(**kw)
    if name == "nli_zeroshot":
        return NliZeroShotBackend(**kw)
    raise ValueError(f"unknown backend {name!r}")


ALL_BACKENDS = ("keyword", "tfidf", "embed_zeroshot", "embed_logreg", "nli_zeroshot")
