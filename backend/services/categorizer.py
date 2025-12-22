# backend/services/categorizer.py

from __future__ import annotations

from pathlib import Path
from typing import Dict

import os
import pandas as pd

from backend.services.category_model import EmbeddingKNNCategoryModel

_BACKEND_DIR = Path(__file__).resolve().parents[1]  # .../backend
ARTIFACT_DIR = _BACKEND_DIR / "models" / "category_knn"

_MODEL = None


def _ensure_model() -> EmbeddingKNNCategoryModel | None:
    global _MODEL
    if _MODEL is not None:
        return _MODEL

    if (ARTIFACT_DIR / "meta.json").exists():
        _MODEL = EmbeddingKNNCategoryModel.load(ARTIFACT_DIR)

        # ---- runtime tuning (NO retrain needed) ----
        _MODEL.top_k = int(os.getenv("CAT_TOPK", "12"))
        _MODEL.min_similarity = float(os.getenv("CAT_MIN_SIM", "0.45"))
        _MODEL.min_winner_share = float(os.getenv("CAT_MIN_SHARE", "0.40"))
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


def _infer_outflow_is_positive(df: pd.DataFrame) -> bool:
    """
    Many credit card statements have:
      - purchases/charges as positive
      - payments/credits as negative

    This tries to infer that convention.
    Returns True if we believe outflows are positive.
    """
    a = pd.to_numeric(df.get("amount", pd.Series([], dtype=float)), errors="coerce").dropna()
    if a.empty:
        return False

    pos = a[a > 0]
    neg = a[a < 0]

    # If we only have one sign, don't flip (bank statements vary)
    if pos.empty or neg.empty:
        return False

    desc = df.get("description", pd.Series([""] * len(df))).astype(str).str.lower()

    payment_like = desc.str.contains(
        r"\b(payment|thank you|autopay|online payment|pmt)\b", regex=True
    )

    # Heuristic signals:
    # - many more positives than negatives
    # - negatives often "payment"
    # - negatives often much larger (monthly payment) than typical purchases
    pos_count = len(pos)
    neg_count = len(neg)
    neg_payment_share = float(payment_like[df["amount"] < 0].mean()) if neg_count else 0.0
    pos_payment_share = float(payment_like[df["amount"] > 0].mean()) if pos_count else 0.0

    pos_median = float(pos.median()) if pos_count else 0.0
    neg_median_abs = float(neg.abs().median()) if neg_count else 0.0

    if (pos_count >= neg_count * 2) and (neg_payment_share >= 0.4) and (pos_payment_share <= 0.2):
        return True

    if (pos_count >= neg_count * 2) and (neg_median_abs > pos_median * 3):
        return True

    return False


def categorize_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds:
      - direction (inflow/outflow/unknown)
      - category
      - category_confidence
      - category_reason
    """
    df = df.copy()

    if "description" not in df.columns:
        df["description"] = ""
    if "amount" not in df.columns:
        df["amount"] = 0.0
    if "date" not in df.columns:
        df["date"] = ""

    df["description"] = df["description"].astype(str).fillna("").str.strip()
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df["date"] = df["date"].apply(_safe_date_to_str)

    outflow_is_positive = _infer_outflow_is_positive(df)

    def direction_from_amount(a):
        try:
            if a is None or (isinstance(a, float) and pd.isna(a)):
                return "unknown"
            a = float(a)
            if a == 0:
                return "unknown"
            if outflow_is_positive:
                return "outflow" if a > 0 else "inflow"
            else:
                return "outflow" if a < 0 else "inflow"
        except Exception:
            return "unknown"

    df["direction"] = df["amount"].apply(direction_from_amount)

    model = _ensure_model()
    if model is None:
        df["category"] = "Uncategorized"
        df["category_confidence"] = 0.0
        df["category_reason"] = "No model artifacts found (backend/models/category_knn). Train the model."
        return df

    cats, confs, reasons = [], [], []
    for _, row in df.iterrows():
        # IMPORTANT: we embed the description only (matches your labeled CSV)
        pred = model.predict_one(row.get("description", ""))
        cats.append(pred.category)
        confs.append(pred.confidence)
        reasons.append(pred.reason)

    df["category"] = cats
    df["category_confidence"] = confs
    df["category_reason"] = reasons
    return df


def build_category_summary(df: pd.DataFrame) -> Dict:
    df = df.copy()
    df["amount"] = pd.to_numeric(df.get("amount", 0.0), errors="coerce").fillna(0.0)

    # Use direction, not sign
    outflows = df[df["direction"] == "outflow"].copy()
    inflows = df[df["direction"] == "inflow"].copy()

    total_outflow = float(outflows["amount"].abs().sum())
    total_inflow = float(inflows["amount"].abs().sum())
    net = total_inflow - total_outflow

    dates = pd.to_datetime(df.get("date", ""), errors="coerce")
    period_start = dates.min().date().isoformat() if not pd.isna(dates.min()) else None
    period_end = dates.max().date().isoformat() if not pd.isna(dates.max()) else None

    overall = {
        "total_inflow": total_inflow,
        "total_outflow": total_outflow,
        "net": float(net),
        "n_transactions": int(len(df)),
        "period_start": period_start,
        "period_end": period_end,
    }

    by_category = []
    if not outflows.empty:
        outflows["spend"] = outflows["amount"].abs()
        grp = outflows.groupby("category", dropna=False)["spend"].agg(["sum", "count"]).reset_index()
        total_spend = float(grp["sum"].sum()) if float(grp["sum"].sum()) != 0 else 1.0
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

    suggestions = []
    for item in by_category[:5]:
        total = item["total"]
        if total <= 0:
            continue
        suggestions.append(
            {
                "category": item["category"],
                "message": f"You spent about {total:.2f} in '{item['category']}'. Reducing this by 10% would save roughly {total * 0.10:.2f} over this statement period.",
            }
        )

    return {"overall": overall, "by_category": by_category, "suggestions": suggestions}
