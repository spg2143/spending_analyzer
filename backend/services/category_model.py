# backend/services/category_model.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer
import re


def _normalize_text(s: str) -> str:
    s = (s or "").strip().lower()

    # Remove common noise patterns (transaction ids, ref numbers, long digit runs)
    s = re.sub(r"\b\d{2,}\b", " ", s)               # remove long numbers
    s = re.sub(r"[\*\#\@\|\/\\]", " ", s)          # remove common separators
    s = re.sub(r"[^a-z\s&\-]", " ", s)             # keep letters, spaces, & and -
    s = re.sub(r"\s+", " ", s).strip()             # collapse whitespace
    return s

@dataclass
class Prediction:
    category: str
    confidence: float
    reason: str


class EmbeddingKNNCategoryModel:
    """
    Embedding-based nearest-neighbor classifier.
    - Fits on labeled examples (text -> category)
    - Predicts by cosine similarity (embeddings are normalized)
    """

    def __init__(
        self,
        model_name: str,
        taxonomy: List[str],
        top_k: int = 8,
        min_similarity: float = 0.55,
        min_winner_share: float = 0.55,
    ) -> None:
        self.model_name = model_name
        self.taxonomy = taxonomy
        self.top_k = top_k
        self.min_similarity = min_similarity
        self.min_winner_share = min_winner_share

        self._encoder: Optional[SentenceTransformer] = None
        self.examples_text: List[str] = []
        self.examples_label: List[str] = []
        self.examples_embedding: Optional[np.ndarray] = None  # shape (n, d)

    def _ensure_encoder(self) -> None:
        if self._encoder is None:
            self._encoder = SentenceTransformer(self.model_name)

    @staticmethod
    def load_taxonomy(path: str | Path) -> List[str]:
        obj = json.loads(Path(path).read_text(encoding="utf-8"))
        return list(obj["categories"])

    # -------------------- Persist --------------------

    def save(self, artifact_dir: str | Path) -> None:
        artifact_dir = Path(artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)

        meta = {
            "model_name": self.model_name,
            "taxonomy": self.taxonomy,
            "top_k": self.top_k,
            "min_similarity": self.min_similarity,
            "min_winner_share": self.min_winner_share,
        }
        (artifact_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        (artifact_dir / "examples.json").write_text(
            json.dumps({"text": self.examples_text, "label": self.examples_label}, indent=2),
            encoding="utf-8",
        )

        if self.examples_embedding is None:
            raise ValueError("No embeddings to save. Train the model first.")
        np.savez_compressed(artifact_dir / "embeddings.npz", embeddings=self.examples_embedding)

    @classmethod
    def load(cls, artifact_dir: str | Path) -> "EmbeddingKNNCategoryModel":
        artifact_dir = Path(artifact_dir)
        meta = json.loads((artifact_dir / "meta.json").read_text(encoding="utf-8"))
        examples = json.loads((artifact_dir / "examples.json").read_text(encoding="utf-8"))
        emb = np.load(artifact_dir / "embeddings.npz")["embeddings"]

        obj = cls(
            model_name=meta["model_name"],
            taxonomy=meta["taxonomy"],
            top_k=int(meta["top_k"]),
            min_similarity=float(meta["min_similarity"]),
            min_winner_share=float(meta["min_winner_share"]),
        )
        obj.examples_text = examples["text"]
        obj.examples_label = examples["label"]
        obj.examples_embedding = emb.astype(np.float32)

        obj._ensure_encoder()
        return obj

    # -------------------- Training --------------------

    def fit_from_labeled_csv(
        self,
        labeled_csv: str | Path,
        text_col: str = "description",
        label_col: str = "category",
        min_examples_per_class: int = 2,
    ) -> None:
        df = pd.read_csv(labeled_csv)

        if text_col not in df.columns or label_col not in df.columns:
            raise ValueError(f"CSV must contain columns: {text_col}, {label_col}")

        df[text_col] = df[text_col].astype(str).map(_normalize_text)
        df[label_col] = df[label_col].astype(str).str.strip()

        df = df[df[label_col].isin(self.taxonomy)].copy()
        if df.empty:
            raise ValueError("No valid labeled rows after filtering by taxonomy.")

        vc = df[label_col].value_counts()
        keep = set(vc[vc >= min_examples_per_class].index)
        df = df[df[label_col].isin(keep)].copy()

        self.examples_text = df[text_col].tolist()
        self.examples_label = df[label_col].tolist()

        self._ensure_encoder()
        X = self._encoder.encode(self.examples_text, normalize_embeddings=True, show_progress_bar=True)
        self.examples_embedding = np.asarray(X, dtype=np.float32)

    # -------------------- Prediction --------------------

    def predict_one(self, text: str) -> Prediction:
        if self.examples_embedding is None or len(self.examples_text) == 0:
            return Prediction(category="Uncategorized", confidence=0.0, reason="Model not trained")

        self._ensure_encoder()
        q = self._encoder.encode([_normalize_text(text)], normalize_embeddings=True)
        q = np.asarray(q, dtype=np.float32)  # (1, d)

        sims = (self.examples_embedding @ q.T).reshape(-1)  # cosine sim
        if sims.size == 0:
            return Prediction(category="Uncategorized", confidence=0.0, reason="No training examples")

        k = min(self.top_k, sims.size)
        top_idx = np.argpartition(-sims, kth=k - 1)[:k]
        top_idx = top_idx[np.argsort(-sims[top_idx])]

        top_sims = sims[top_idx]
        top_labels = [self.examples_label[i] for i in top_idx]
        top_texts = [self.examples_text[i] for i in top_idx]

        best_sim = float(top_sims[0])
        if best_sim < self.min_similarity:
            return Prediction(
                category="Uncategorized",
                confidence=best_sim,
                reason=f"Low similarity (best={best_sim:.3f})",
            )

        # Weighted vote
        scores: Dict[str, float] = {}
        for lab, sim in zip(top_labels, top_sims):
            scores[lab] = scores.get(lab, 0.0) + float(sim)

        winner = max(scores.items(), key=lambda x: x[1])[0]
        total = sum(scores.values()) + 1e-9
        winner_share = scores[winner] / total

        if winner_share < self.min_winner_share:
            return Prediction(
                category="Uncategorized",
                confidence=float(winner_share),
                reason=f"Uncertain vote (share={winner_share:.3f}, best={best_sim:.3f})",
            )

        reason = f"Top match: '{top_texts[0]}' (sim={best_sim:.3f})"
        return Prediction(category=winner, confidence=float(winner_share), reason=reason)
