from __future__ import annotations

from pathlib import Path
from typing import IO, Optional
import io
import re

import pandas as pd
import pdfplumber

SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".pdf"}


class UnsupportedFileTypeError(Exception):
    """Raised when the uploaded file type is not supported."""
    pass


def load_statement_from_upload(filename: str, file_bytes: bytes) -> pd.DataFrame:
    """
    Main entry point – used by the upload route.

    Returns a pandas DataFrame with at least:
        - date (datetime64)
        - description (str)
        - amount (float, signed: +inflow, -outflow)
    """
    ext = Path(filename).suffix.lower()

    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileTypeError(
            f"Unsupported file type: {ext}. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    buffer = io.BytesIO(file_bytes)

    if ext == ".pdf":
        # Use custom PDF parser for BoA-style statements.
        df = _load_bofa_pdf(buffer)
    elif ext == ".csv":
        df = pd.read_csv(buffer)
        df = _standardize_column_names(df)
        df = _clean_transaction_df(df)
    elif ext in {".xlsx", ".xls"}:
        df = pd.read_excel(buffer)
        df = _standardize_column_names(df)
        df = _clean_transaction_df(df)
    else:
        # Should not reach here due to SUPPORTED_EXTENSIONS check.
        raise UnsupportedFileTypeError(f"Unsupported file type: {ext}")

    if df is None or df.empty:
        raise ValueError("No transactions parsed from file.")

    return df


# ---------- PDF (BoA-style) parsing ----------

def _load_bofa_pdf(buffer: IO[bytes]) -> pd.DataFrame:
    """
    Extract transactions from a Bank of America-style credit card statement PDF.

    Strategy:
      - Find pages containing "Transactions".
      - Within those pages, look for lines starting with:
            MM/DD<space>MM/DD<space>...
        which are "Transaction Date" and "Posting Date".
      - Split the remainder of the line into:
            description, (optional ref#), (optional acct#), amount

    Returns a DataFrame with at least:
        date (transaction date)
        description
        amount

    and extra columns:
        posting_date, reference_number, account_number, section
    """
    records = []

    with pdfplumber.open(buffer) as pdf:
        # Try to infer the statement year from header like:
        # "November 6 - December 5, 2025"
        statement_year = _infer_statement_year(pdf)
        if statement_year is None:
            # Fallback: pick a recent year; you can tweak if needed
            statement_year = 2025

        for page in pdf.pages:
            text = page.extract_text() or ""
            if "Transactions" not in text:
                continue

            lines = [ln.strip() for ln in text.splitlines()]
            in_transactions = False
            current_section = None

            for line in lines:
                if not line:
                    continue

                # Start of block
                if line == "Transactions":
                    in_transactions = True
                    continue

                if not in_transactions:
                    continue

                # End at page footer
                if line.startswith("Page ") and " of " in line:
                    break

                # Skip column headers
                if line.startswith("Transaction Posting Reference Account"):
                    continue
                if line.startswith("Date Date Description"):
                    continue

                # Section headers within Transactions
                if line in (
                    "Payments and Other Credits",
                    "Purchases and Adjustments",
                    "Interest Charged",
                ):
                    current_section = line
                    continue

                # Skip TOTAL lines (summary, not single transactions)
                if line.startswith("TOTAL "):
                    continue

                # Match "MM/DD  MM/DD  <rest>"
                m = re.match(r"^(\d{2}/\d{2})\s+(\d{2}/\d{2})\s+(.+)$", line)
                if not m:
                    continue

                tran_mmdd, post_mmdd, rest = m.groups()
                tokens = rest.split()
                if not tokens:
                    continue

                amount_token = tokens[-1]

                # Heuristic for ref & acct numbers:
                # ... <reference_number> <account_number> <amount>
                cleaned_amount = amount_token.replace(",", "").replace("$", "").strip()
                ref = None
                acct = None

                if (
                    len(tokens) >= 3
                    and cleaned_amount.replace(".", "").replace("-", "").isdigit()
                    and tokens[-2].isdigit()
                    and tokens[-3].isdigit()
                ):
                    ref = tokens[-2]
                    acct = tokens[-3]
                    desc_tokens = tokens[:-3]
                else:
                    desc_tokens = tokens[:-1]

                description = " ".join(desc_tokens).strip()

                tran_date_str = f"{tran_mmdd}/{statement_year}"
                post_date_str = f"{post_mmdd}/{statement_year}"

                records.append(
                    {
                        "transaction_date_str": tran_date_str,
                        "posting_date_str": post_date_str,
                        "description": description,
                        "reference_number": ref,
                        "account_number": acct,
                        "amount_raw": amount_token,
                        "section": current_section,
                    }
                )

    if not records:
        raise ValueError("No transaction lines found in PDF.")

    df = pd.DataFrame(records)

    # Convert dates
    df["date"] = pd.to_datetime(
        df["transaction_date_str"], format="%m/%d/%Y", errors="coerce"
    )
    df["posting_date"] = pd.to_datetime(
        df["posting_date_str"], format="%m/%d/%Y", errors="coerce"
    )

    # Parse amount
    df["amount"] = df["amount_raw"].apply(_parse_amount)

    # Keep only rows with valid amount (and date if available)
    df = df[df["amount"].notna()]
    if "date" in df.columns:
        df = df[df["date"].notna()]

    # Ensure description exists
    df["description"] = df["description"].fillna("").astype(str).str.strip()

    # Select core + useful extra columns
    cols = ["date", "description", "amount"]
    extra_cols = ["posting_date", "reference_number", "account_number", "section"]
    for c in extra_cols:
        if c in df.columns:
            cols.append(c)

    df = df[cols].reset_index(drop=True)
    return df


def _infer_statement_year(pdf) -> Optional[int]:
    """
    Try to extract the year from a header line like:
        'November 6 - December 5, 2025'
    """
    header_pattern = re.compile(
        r"[A-Za-z]+\s+\d{1,2}\s*-\s*[A-Za-z]+\s+\d{1,2},\s*(\d{4})"
    )
    for page in pdf.pages:
        text = page.extract_text() or ""
        m = header_pattern.search(text)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue
    return None


def _parse_amount(s: str) -> Optional[float]:
    """
    Convert a money-like string into float.
    Handles:
        - thousands separators (1,234.56)
        - dollar signs
        - parentheses as negatives, e.g. (123.45)
    """
    s = str(s)
    s = s.replace(",", "").replace("$", "").strip()
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    return pd.to_numeric(s, errors="coerce")


# ---------- Generic CSV/Excel cleaning ----------

def _standardize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """
    Standardize column names for CSV/Excel/PDF to match what we expect.

    Canonical names we use everywhere else:
        - date
        - posting_date
        - description
        - amount
        - debit
        - credit
        - balance
    """
    col_map = {}

    for col in df.columns:
        col_str = str(col).strip()
        col_lower = col_str.lower()

        # ---- DATE-LIKE ----
        if col_lower in {
            "date",
            "transaction date",
            "transaction_date",
            "date of transaction",
        }:
            col_map[col] = "date"

        # ---- POSTING DATE ----
        elif col_lower in {
            "posting date",
            "posting_date",
            "posted date",
            "post date",
        }:
            col_map[col] = "posting_date"

        # ---- DESCRIPTION-LIKE ----
        elif any(
            key in col_lower
            for key in ("description", "details", "narration", "memo", "text", "note")
        ):
            col_map[col] = "description"

        # ---- AMOUNT-LIKE (but not debit/credit) ----
        elif (
            ("amount" in col_lower or "amt" in col_lower)
            and "debit" not in col_lower
            and "credit" not in col_lower
        ):
            col_map[col] = "amount"

        # ---- DEBIT / CREDIT / BALANCE ----
        elif "debit" in col_lower:
            col_map[col] = "debit"
        elif "credit" in col_lower:
            col_map[col] = "credit"
        elif "balance" in col_lower:
            col_map[col] = "balance"

    # Apply renaming
    df = df.rename(columns=col_map)

    # Safety net: drop duplicate columns, keep first occurrence
    df = df.loc[:, ~df.columns.duplicated()]

    return df



def _clean_transaction_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean generic bank statement DataFrame:
      - merge debit/credit into signed 'amount'
      - numeric conversion
      - date parsing
      - basic description cleanup
    """
    # Merge debit/credit into amount
    if {"debit", "credit"} & set(df.columns):
        if "amount" not in df.columns:
            df["amount"] = 0.0

        if "debit" in df.columns:
            debit = _to_numeric(df["debit"])
            df["amount"] = df["amount"].where(debit.isna(), -debit)

        if "credit" in df.columns:
            credit = _to_numeric(df["credit"])
            df["amount"] = df["amount"].where(credit.isna(), credit)

    # Amount numeric
    if "amount" in df.columns:
        df["amount"] = _to_numeric(df["amount"])
        df = df[df["amount"].notna()]

    # Date parsing
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")

    # Description cleaning
    if "description" in df.columns:
        df["description"] = df["description"].astype(str).str.strip()
    else:
        df["description"] = ""

    # Drop rows missing both date and amount (if both columns exist)
    important_cols = [c for c in ["date", "amount"] if c in df.columns]
    if important_cols:
        df = df.dropna(subset=important_cols, how="all")

    df = df.reset_index(drop=True)
    return df


def _to_numeric(series: pd.Series) -> pd.Series:
    """
    Convert a Series with money-like strings into floats.
    """
    s = (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("$", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace("\u00a0", "", regex=False)
        .str.strip()
    )
    s = s.str.replace(r"^\((.*)\)$", r"-\1", regex=True)
    return pd.to_numeric(s, errors="coerce")
