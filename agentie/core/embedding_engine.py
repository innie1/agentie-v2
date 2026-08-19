from __future__ import annotations

import hashlib
import math
import os
import re
import threading
from functools import lru_cache
from typing import Iterable

_DIM = 384
_MODEL = None
_MODEL_LOCK = threading.Lock()


def backend_name() -> str:
    mode = os.getenv("AGENTIE_EMBEDDING_BACKEND", "auto").strip().lower()
    if mode in {"hash", "hashed", "offline"}:
        return "hash"
    try:
        import fastembed  # noqa: F401
        return "fastembed"
    except Exception:
        return "hash"


def _model():
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    with _MODEL_LOCK:
        if _MODEL is not None:
            return _MODEL
        from fastembed import TextEmbedding
        model_name = os.getenv("AGENTIE_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5").strip()
        _MODEL = TextEmbedding(model_name=model_name)
        return _MODEL


def _tokens(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", (text or "").lower()).strip()
    words = re.findall(r"[a-z0-9][a-z0-9_-]{1,}", text)
    grams: list[str] = []
    for word in words:
        grams.append("w:" + word)
        padded = f"^{word}$"
        for n in (3, 4):
            grams.extend(f"c{n}:" + padded[i:i+n] for i in range(max(0, len(padded)-n+1)))
    for a, b in zip(words, words[1:]):
        grams.append("b:" + a + "_" + b)
    return grams


def _hash_embedding(text: str, dim: int = _DIM) -> list[float]:
    vec = [0.0] * dim
    for token in _tokens(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        raw = int.from_bytes(digest, "little")
        idx = raw % dim
        sign = -1.0 if (raw >> 9) & 1 else 1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v*v for v in vec)) or 1.0
    return [v / norm for v in vec]


@lru_cache(maxsize=2048)
def embed_text(text: str) -> tuple[float, ...]:
    clean = re.sub(r"\s+", " ", (text or "").strip())[:12000]
    if not clean:
        return tuple([0.0] * _DIM)
    if backend_name() == "fastembed":
        try:
            vector = next(iter(_model().embed([clean])))
            values = [float(x) for x in vector]
            norm = math.sqrt(sum(v*v for v in values)) or 1.0
            return tuple(v / norm for v in values)
        except Exception:
            pass
    return tuple(_hash_embedding(clean))


def embed_many(texts: Iterable[str]) -> list[list[float]]:
    clean = [re.sub(r"\s+", " ", (t or "").strip())[:12000] for t in texts]
    if backend_name() == "fastembed" and clean:
        try:
            vectors = []
            for vector in _model().embed(clean):
                values = [float(x) for x in vector]
                norm = math.sqrt(sum(v*v for v in values)) or 1.0
                vectors.append([v / norm for v in values])
            return vectors
        except Exception:
            pass
    return [_hash_embedding(t) for t in clean]


def cosine(a: Iterable[float], b: Iterable[float]) -> float:
    av = list(a); bv = list(b)
    if not av or not bv:
        return 0.0
    n = min(len(av), len(bv))
    return max(-1.0, min(1.0, sum(av[i] * bv[i] for i in range(n))))
