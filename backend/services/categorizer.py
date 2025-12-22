# backend/services/categorizer.py

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from backend.services.category_model import EmbeddingKNNCategoryModel
from sqlalchemy.orm import Session
from backend.repositories.vendor_map_repo import get_vendor_map

_BACKEND_DIR = Path(__file__).resolve().parents[1]  # .../backend
ARTIFACT_DIR = _BACKEND_DIR / "models" / "category_knn"
RULES_PATH = _BACKEND_DIR / "data" / "merchant_rules.json"

_MODEL = None
_RULES: List[Tuple[re.Pattern, str, int]] = []  # (compiled_regex, category, priority)

# Config knobs
REVIEW_THRESHOLD = float(os.getenv("CAT_REVIEW_THRESHOLD", "0.55"))
FALLBACK_OUTFLOW_CATEGORY = os.getenv("FALLBACK_OUTFLOW_CATEGORY", "Other Expense")


TRANSFER_REGEX = re.compile(
    r"\b(payment|pmt|autopay|online\s*payment|thank\s*you|credit\s*card\s*payment|card\s*payment)\b",
    flags=re.IGNORECASE,
)

NOISE_PREFIXES = re.compile(
    r"^(tst|sq|pp|clr|bh|dd|gp|py)\*+\s*|^(tst|sq|pp|clr|bh)\s+",
    flags=re.IGNORECASE,
)


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


def _normalize_text(s: str) -> str:
    """
    General cleanup for matching and embedding.
    """
    s = (s or "").lower().strip()
    s = re.sub(r"\b\d{2,}\b", " ", s)        # long numbers
    s = re.sub(r"[\*\#\@\|\/\\]", " ", s)    # separators
    s = re.sub(r"[^a-z\s&\-]", " ", s)       # keep letters, spaces, & and -
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _extract_vendor(description: str) -> str:
    """
    Pull a stable vendor string out of noisy statement descriptions.
    Examples:
      "TST*TIN BUILDING QSRS New York NY" -> "tin building"
      "SQ *HOODA HALAL ..." -> "hooda halal"
      "PP* ANUM CRYSTAL ..." -> "anum crystal"
      "UBER *TRIP HELP.UBER.COM CA" -> "uber"
    """
    d = (description or "").strip()

    # Remove leading noise prefixes
    d = NOISE_PREFIXES.sub("", d)

    # Normalize
    d = _normalize_text(d)

    # Remove common trailing location tokens (very light heuristic)
    # You can extend this list later if needed.
    stop = {"new", "york", "ny", "ca", "ct", "nj", "springs", "saratoga", "norwalk"}
    toks = [t for t in d.split() if t not in stop]

    # Vendor = first 1–4 tokens
    vendor = " ".join(toks[:4]).strip()
    return vendor


def _load_rules_once() -> None:
    global _RULES
    if _RULES:
        return

    if not RULES_PATH.exists():
        _RULES = []
        return

    raw = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    rules = []
    for r in raw:
        pat = re.compile(r["pattern"], flags=re.IGNORECASE)
        rules.append((pat, r["category"], int(r.get("priority", 0))))
    rules.sort(key=lambda x: x[2], reverse=True)  # higher priority first
    _RULES = rules


def reload_rules() -> None:
    """
    Call this if you change merchant_rules.json while the server is running.
    """
    global _RULES
    _RULES = []


def _ensure_model() -> EmbeddingKNNCategoryModel | None:
    global _MODEL
    if _MODEL is not None:
        return _MODEL

    if (ARTIFACT_DIR / "meta.json").exists():
        _MODEL = EmbeddingKNNCategoryModel.load(ARTIFACT_DIR)

        # Runtime tuning (no retrain needed)
        _MODEL.top_k = int(os.getenv("CAT_TOPK", "12"))
        _MODEL.min_similarity = float(os.getenv("CAT_MIN_SIM", "0.45"))
        _MODEL.min_winner_share = float(os.getenv("CAT_MIN_SHARE", "0.40"))
        return _MODEL

    return None


def _infer_outflow_is_positive(df: pd.DataFrame) -> bool:
    """
    Credit card statements commonly have purchases positive, payments negative.
    Bank account statements often have expenses negative, income positive.
    We infer which convention is used.
    """
    a = pd.to_numeric(df.get("amount", pd.Series([], dtype=float)), errors="coerce").dropna()
    if a.empty:
        return False

    pos = a[a > 0]
    neg = a[a < 0]
    if pos.empty or neg.empty:
        return False

    desc = df.get("description", pd.Series([""] * len(df))).astype(str)
    payment_like = desc.apply(lambda x: bool(TRANSFER_REGEX.search(str(x))))

    pos_count, neg_count = len(pos), len(neg)
    neg_payment_share = float(payment_like[df["amount"] < 0].mean()) if neg_count else 0.0
    pos_payment_share = float(payment_like[df["amount"] > 0].mean()) if pos_count else 0.0

    pos_median = float(pos.median()) if pos_count else 0.0
    neg_median_abs = float(neg.abs().median()) if neg_count else 0.0

    if (pos_count >= neg_count * 2) and (neg_payment_share >= 0.35) and (pos_payment_share <= 0.2):
        return True

    if (pos_count >= neg_count * 2) and (neg_median_abs > pos_median * 3):
        return True

    return False


def _direction_from_desc_and_amount(desc: str, amount: float, outflow_is_positive: bool) -> str:
    if TRANSFER_REGEX.search(desc or ""):
        return "transfer"

    if amount is None or (isinstance(amount, float) and pd.isna(amount)):
        return "unknown"
    if float(amount) == 0.0:
        return "unknown"

    if outflow_is_positive:
        return "outflow" if amount > 0 else "inflow"
    return "outflow" if amount < 0 else "inflow"


def _apply_rules(text: str) -> str | None:
    _load_rules_once()
    t = _normalize_text(text)
    for pat, cat, _prio in _RULES:
        if pat.search(t):
            return cat
    return None


def categorize_transactions(df: pd.DataFrame, db: Session | None = None) -> pd.DataFrame:
    
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

    # NEW: vendor column
    df["vendor"] = df["description"].apply(_extract_vendor)
    
    # 0) DB vendor map first (highest precision, persistent)
    if db is not None:
        vendor_to_category = get_vendor_map(db, df["vendor"].tolist())
        if vendor_to_category:
            for i, v in enumerate(df["vendor"].tolist()):
                if v in vendor_to_category:
                    df.at[i, "category"] = vendor_to_category[v]
                    df.at[i, "category_confidence"] = 1.0
                    df.at[i, "category_reason"] = "vendor_map_db"
                    df.at[i, "needs_review"] = False

    outflow_is_positive = _infer_outflow_is_positive(df)

    df["direction"] = [
        _direction_from_desc_and_amount(d, a, outflow_is_positive)
        for d, a in zip(df["description"].tolist(), df["amount"].tolist())
    ]

    df["category"] = None
    df["category_confidence"] = 0.0
    df["category_reason"] = ""
    df["needs_review"] = False

    # 1) RULES FIRST (vendor first, then description)
    for i, row in df.iterrows():
        v = row.get("vendor", "") or ""
        d = row.get("description", "") or ""

        cat = _apply_rules(v) or _apply_rules(d)
        if cat:
            df.at[i, "category"] = cat
            df.at[i, "category_confidence"] = 1.0
            df.at[i, "category_reason"] = "merchant_rule"

    # 2) ML for remaining (use vendor + normalized description)
    model = _ensure_model()
    if model is not None:
        for i, row in df[df["category"].isna()].iterrows():
            vendor = row.get("vendor", "") or ""
            desc = row.get("description", "") or ""

            query = _normalize_text(f"{vendor} {desc}".strip())
            pred = model.predict_one(query)

            df.at[i, "category"] = pred.category
            df.at[i, "category_confidence"] = float(pred.confidence)
            df.at[i, "category_reason"] = pred.reason

    # 3) FINAL POLICY (transfer + fallback)
    for i, row in df.iterrows():
        cat = row["category"]
        direction = row.get("direction", "unknown")

        if direction == "transfer":
            df.at[i, "category"] = "Transfers"
            df.at[i, "category_confidence"] = max(float(df.at[i, "category_confidence"]), 0.9)
            df.at[i, "category_reason"] = df.at[i, "category_reason"] or "transfer_detected"
            df.at[i, "needs_review"] = False
            continue

        # If model abstained or unknown
        if cat in (None, "", "Uncategorized"):
            if direction == "outflow":
                df.at[i, "category"] = FALLBACK_OUTFLOW_CATEGORY
                df.at[i, "category_confidence"] = max(float(df.at[i, "category_confidence"]), 0.2)
                df.at[i, "category_reason"] = "fallback_outflow"
                df.at[i, "needs_review"] = True
            else:
                df.at[i, "category"] = "Uncategorized"
                df.at[i, "category_reason"] = df.at[i, "category_reason"] or "no_match"
                df.at[i, "needs_review"] = True
            continue

        # Low confidence → mark for review (even if categorized)
        conf = float(row.get("category_confidence", 0.0) or 0.0)
        if conf < REVIEW_THRESHOLD:
            df.at[i, "needs_review"] = True

    return df


def build_category_summary(df: pd.DataFrame) -> Dict:
    df = df.copy()
    df["amount"] = pd.to_numeric(df.get("amount", 0.0), errors="coerce").fillna(0.0)

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
        "needs_review_count": int(df.get("needs_review", False).sum()) if "needs_review" in df.columns else 0,
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
