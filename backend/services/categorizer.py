# backend/services/categorizer.py

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from backend.services.category_model import EmbeddingKNNCategoryModel

# Paths (match your repo layout)
_BACKEND_DIR = Path(__file__).resolve().parents[1]  # .../backend
TAXONOMY_PATH = _BACKEND_DIR / "data" / "category_taxonomy.json"
ARTIFACT_DIR = _BACKEND_DIR / "models" / "category_knn"  # new artifacts live here

# Global cached model (loaded once)
_MODEL = None


def _ensure_model() -> EmbeddingKNNCategoryModel | None:
    global _MODEL
    if _MODEL is not None:
        return _MODEL

    if (ARTIFACT_DIR / "meta.json").exists():
        _MODEL = EmbeddingKNNCategoryModel.load(ARTIFACT_DIR)
        return _MODEL

    return None


def _safe_date_to_str(x) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return ""
    try:
        dt = pd.to_datetime(x, errors="coerce")
        if pd.isna(dt):
            return str(x)[:10]
        return dt.date().isoformat()
    except Exception:
        return str(x)[:10]


def _direction_from_amount(a) -> str:
    try:
        if a is None or (isinstance(a, float) and pd.isna(a)):
            return "unknown"
        a = float(a)
        if a > 0:
            return "inflow"
        if a < 0:
            return "outflow"
        return "unknown"
    except Exception:
        return "unknown"


def _build_model_text(description: str, direction: str) -> str:
    # Add direction token to help model separate income vs spend
    desc = (description or "").strip()
    return f"{desc} | {direction}"


def categorize_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds:
      - direction
      - category
      - category_confidence
      - category_reason
    """
    df = df.copy()

    # Ensure expected columns exist
    if "description" not in df.columns:
        df["description"] = ""
    if "amount" not in df.columns:
        df["amount"] = 0.0
    if "date" not in df.columns:
        df["date"] = ""

    # Normalize
    df["description"] = df["description"].astype(str).fillna("").str.strip()
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df["direction"] = df["amount"].apply(_direction_from_amount)

    # Convert date to string early for JSON safety
    df["date"] = df["date"].apply(_safe_date_to_str)

    model = _ensure_model()

    if model is None:
        # No artifacts yet -> fallback
        df["category"] = "Uncategorized"
        df["category_confidence"] = 0.0
        df["category_reason"] = "No model artifacts found. Train model to enable categorization."
        return df

    cats = []
    confs = []
    reasons = []

    for _, row in df.iterrows():
        text = _build_model_text(row.get("description", ""), row.get("direction", "unknown"))
        pred = model.predict_one(text)
        cats.append(pred.category)
        confs.append(pred.confidence)
        reasons.append(pred.reason)

    df["category"] = cats
    df["category_confidence"] = confs
    df["category_reason"] = reasons
    return df


def build_category_summary(df: pd.DataFrame) -> Dict:
    """
    Returns the shape your frontend expects:
      summary = {
        overall: {...},
        by_category: [...],
        suggestions: [...]
      }
    """
    df = df.copy()
    df["amount"] = pd.to_numeric(df.get("amount", 0.0), errors="coerce").fillna(0.0)

    # Overall
    inflow = df.loc[df["amount"] > 0, "amount"].sum()
    outflow = df.loc[df["amount"] < 0, "amount"].abs().sum()
    net = inflow - outflow
    n_transactions = len(df)

    # Statement period (best effort)
    dates = pd.to_datetime(df.get("date", ""), errors="coerce")
    period_start = dates.min().date().isoformat() if not pd.isna(dates.min()) else None
    period_end = dates.max().date().isoformat() if not pd.isna(dates.max()) else None

    overall = {
        "total_inflow": float(inflow),
        "total_outflow": float(outflow),
        "net": float(net),
        "n_transactions": int(n_transactions),
        "period_start": period_start,
        "period_end": period_end,
    }

    # Spending by category (only outflows)
    spend_df = df[df["amount"] < 0].copy()
    spend_df["spend"] = spend_df["amount"].abs()

    by_category = []
    if not spend_df.empty:
        grp = spend_df.groupby("category", dropna=False)["spend"].agg(["sum", "count"]).reset_index()
        total_spend = grp["sum"].sum() if grp["sum"].sum() != 0 else 1.0
        grp["share"] = grp["sum"] / total_spend

        grp = grp.sort_values("sum", ascending=False)
        for _, r in grp.iterrows():
            by_category.append(
                {
                    "category": str(r["category"]) if pd.notna(r["category"]) else "Uncategorized",
                    "total": float(r["sum"]),
                    "count": int(r["count"]),
                    "share": float(r["share"]),
                }
            )

    # Suggestions (simple heuristic: top categories)
    suggestions = []
    for item in by_category[:5]:
        cat = item["category"]
        total = item["total"]
        if total <= 0:
            continue
        save_10 = total * 0.10
        suggestions.append(
            {
                "category": cat,
                "message": f"You spent about {total:.2f} in '{cat}'. Reducing this by 10% would save roughly {save_10:.2f} over this statement period.",
            }
        )

    return {"overall": overall, "by_category": by_category, "suggestions": suggestions}
