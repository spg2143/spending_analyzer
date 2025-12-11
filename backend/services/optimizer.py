# backend/services/optimizer.py
from __future__ import annotations
from typing import List, Dict, Any


def build_suggestions(category_expenses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Take category expense breakdown and propose a few simple savings ideas.

    Input: list of dicts with keys: category, total, count, share
           where total is a positive spend number.

    Output: list of {category, potential_saving, message}
    """
    if not category_expenses:
        return []

    # Sort categories by largest spend
    sorted_expenses = sorted(category_expenses, key=lambda x: x["total"], reverse=True)

    # Focus on top 3 spending categories
    top_categories = sorted_expenses[:3]

    suggestions: List[Dict[str, Any]] = []
    for cat in top_categories:
        category = cat["category"]
        total = float(cat["total"])
        potential_saving = round(total * 0.1, 2)  # hypothetical 10% cut

        message = (
            f"You spent about {total:.2f} in '{category}'. "
            f"Reducing this by just 10% would save roughly {potential_saving:.2f} "
            f"over the period of this statement."
        )

        suggestions.append(
            {
                "category": category,
                "potential_saving": potential_saving,
                "message": message,
            }
        )

    return suggestions
