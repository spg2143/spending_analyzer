from __future__ import annotations

import pandas as pd
from typing import Dict, Any, List

from .optimizer import build_suggestions

EXPENSE_CATEGORY_KEYWORDS = {
    "Rent & Office": ["rent", "office", "cowork", "wework"],
    "Utilities": ["utility", "utilities", "electric", "gas", "wasser", "water", "energie"],
    "Payroll & Contractors": [
        "salary",
        "payroll",
        "wage",
        "paychex",
        "gusto",
        "upwork",
        "freelance",
        "contractor",
    ],
    "Travel & Transport": [
        "uber",
        "lyft",
        "taxi",
        "bahn",
        "train",
        "flight",
        "airline",
        "hotel",
        "airbnb",
        "fuel",
        "gasstation",
        "shell",
        "esso",
        "bp",
    ],
    "Supplies & Inventory": [
        "stationery",
        "staples",
        "office depot",
        "inventory",
        "stock",
        "supplies",
    ],
    "Software & Subscriptions": [
        "saas",
        "subscription",
        "subscript",
        "aws",
        "azure",
        "gcp",
        "google workspace",
        "microsoft",
        "office365",
        "adobe",
        "slack",
        "zoom",
        "shopify plan",
        "quickbooks",
    ],
    "Advertising & Marketing": [
        "adwords",
        "google ads",
        "facebook ads",
        "instagram ads",
        "linkedin ads",
        "meta ads",
        "campaign",
        "marketing",
        "advertising",
    ],
    "Bank & Fees": [
        "fee",
        "charges",
        "charge",
        "overdraft",
        "interest",
        "commission",
        "processing",
    ],
    "Taxes": [
        "tax",
        "vat",
        "gst",
        "finanzamt",
        "irs",
        "revenue service",
    ],
    "Other Expense": [],
}

INCOME_CATEGORY_KEYWORDS = {
    "Sales Income": [
        "stripe",
        "shopify",
        "paypal",
        "square",
        "pos",
        "card payment",
        "customer payment",
        "invoice",
    ],
    "Interest & Other Income": [
        "interest",
        "refund",
        "rebate",
        "cashback",
    ],
    "Owner Contribution": [
        "capital",
        "owner",
        "contribution",
        "equity",
    ],
    "Other Income": [],
}


def categorize_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds:
        - direction: "inflow", "outflow" or "zero"
        - category: category string
    """
    if "amount" not in df.columns:
        df["direction"] = "unknown"
        df["category"] = "Uncategorized"
        return df

    df["direction"] = df["amount"].apply(
        lambda x: "inflow" if x > 0 else ("outflow" if x < 0 else "zero")
    )

    if "description" not in df.columns:
        df["description"] = ""

    df["description_filled"] = df["description"].fillna("").astype(str)

    df["category"] = df.apply(
        lambda row: _assign_category(row["description_filled"], row["direction"]), axis=1
    )

    df = df.drop(columns=["description_filled"])
    return df


def _assign_category(description: str, direction: str) -> str:
    desc = description.lower()

    if direction == "outflow":
        for category, keywords in EXPENSE_CATEGORY_KEYWORDS.items():
            if any(kw in desc for kw in keywords):
                return category
        return "Other Expense"

    elif direction == "inflow":
        for category, keywords in INCOME_CATEGORY_KEYWORDS.items():
            if any(kw in desc for kw in keywords):
                return category
        return "Other Income"

    else:
        return "Uncategorized"


def build_category_summary(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Build a JSON-friendly summary:
        - overall totals
        - category breakdown
        - monthly summary (if dates exist)
        - suggestions
    """
    if "amount" in df.columns:
        total_inflow = df.loc[df["amount"] > 0, "amount"].sum()
        total_outflow = df.loc[df["amount"] < 0, "amount"].sum()
    else:
        total_inflow = 0.0
        total_outflow = 0.0

    net = total_inflow + total_outflow

    if "date" in df.columns and pd.api.types.is_datetime64_any_dtype(df["date"]):
        period_start = df["date"].min()
        period_end = df["date"].max()
        period_start_str = period_start.strftime("%Y-%m-%d") if pd.notna(period_start) else None
        period_end_str = period_end.strftime("%Y-%m-%d") if pd.notna(period_end) else None
    else:
        period_start_str = None
        period_end_str = None

    category_expenses: List[Dict[str, Any]] = []
    if "category" in df.columns and "amount" in df.columns:
        outflows = df[df["amount"] < 0].copy()
        if not outflows.empty:
            grouped = outflows.groupby("category")["amount"].agg(["sum", "count"]).reset_index()
            total_abs_outflow = -grouped["sum"].sum()

            for _, row in grouped.sort_values("sum").iterrows():
                category = row["category"]
                total = float(-row["sum"])
                count = int(row["count"])
                share = float(total / total_abs_outflow) if total_abs_outflow > 0 else 0.0

                category_expenses.append(
                    {
                        "category": category,
                        "total": round(total, 2),
                        "count": count,
                        "share": round(share, 4),
                    }
                )

    monthly_summary: List[Dict[str, Any]] = []
    if "date" in df.columns and pd.api.types.is_datetime64_any_dtype(df["date"]):
        df["year_month"] = df["date"].dt.to_period("M").astype(str)
        grouped_month = (
            df.groupby("year_month")["amount"]
            .agg(total="sum", inflow=lambda s: s[s > 0].sum(), outflow=lambda s: s[s < 0].sum())
            .reset_index()
        )
        for _, row in grouped_month.iterrows():
            ym = row["year_month"]
            inflow = float(row["inflow"])
            outflow = float(row["outflow"])
            monthly_summary.append(
                {
                    "month": ym,
                    "inflow": round(inflow, 2),
                    "outflow": round(outflow, 2),
                    "net": round(float(row["total"]), 2),
                }
            )

    suggestions = build_suggestions(category_expenses)

    return {
        "overall": {
            "total_inflow": round(float(total_inflow), 2),
            "total_outflow": round(float(total_outflow), 2),
            "net": round(float(net), 2),
            "n_transactions": int(len(df)),
            "period_start": period_start_str,
            "period_end": period_end_str,
        },
        "by_category": category_expenses,
        "by_month": monthly_summary,
        "suggestions": suggestions,
    }
