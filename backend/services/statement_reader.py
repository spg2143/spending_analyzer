from __future__ import annotations

from pathlib import Path
from typing import IO, Optional
import io
import re

import pandas as pd
import pdfplumber

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".pdf"}


class UnsupportedFileTypeError(Exception):
    """Raised when the uploaded file type is not supported."""
    pass


def load_statement_from_upload(
    filename: str,
    file_bytes: bytes,
    page_start: Optional[int] = None,
    page_end: Optional[int] = None,
) -> pd.DataFrame:
    """
    Main entry point – used by the upload route.

    For PDFs, uses a *generic* transaction parser that should work with
    most card / bank statements (including Chase and BoA) as long as:
        - each transaction is on a single line
        - the line starts with a date like '11/04'
        - the line ends with an amount like '23.93' or '-1,066.82'

    Returns a pandas DataFrame with at least:
        - date (datetime64)
        - description (str)
        - amount (float, signed exactly as in the statement)
    """
    ext = Path(filename).suffix.lower()

    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileTypeError(
            f"Unsupported file type: {ext}. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    buffer = io.BytesIO(file_bytes)

    if ext == ".pdf":
        df = _load_pdf_transactions(buffer, page_start=page_start, page_end=page_end)
    elif ext == ".csv":
        df = pd.read_csv(buffer)
        df = _standardize_column_names(df)
        df = _clean_transaction_df(df)
    elif ext in {".xlsx", ".xls"}:
        df = pd.read_excel(buffer)
        df = _standardize_column_names(df)
        df = _clean_transaction_df(df)
    else:
        raise UnsupportedFileTypeError(f"Unsupported file type: {ext}")

    if df is None or df.empty:
        raise ValueError("No transactions parsed from file.")

    return df


# ---------------------------------------------------------------------------
# Generic PDF transaction parser
# ---------------------------------------------------------------------------

def _load_pdf_transactions(
    buffer: IO[bytes],
    page_start: Optional[int] = None,
    page_end: Optional[int] = None,
) -> pd.DataFrame:
    """
    Generic PDF transaction parser.

    Works for Chase (example statement you uploaded) and BoA type layouts
    by looking for lines matching:

        MM/DD  <description>  <amount>

    Examples of lines this will pick up (from your Chase PDF :contentReference[oaicite:1]{index=1}):

        11/04 Payment Thank You-Mobile -594.12
        10/28 UBER *TRIP HELP.UBER.COM CA 23.93
        11/14 OPENAI *CHATGPT SUBSCR OPENAI.COM CA 21.78
        11/25 JUBILEE MARKET PLACE NEW YORK NY 34.69

    And BoA-style:

        11/10 11/11 BH* BETTERHELP BETTERHELP.CO CA 65.00

    (the second date is treated as part of the description).
    """
    records: list[dict] = []

    with pdfplumber.open(buffer) as pdf:
        n_pages = len(pdf.pages)
        if n_pages == 0:
            raise ValueError("PDF has no pages.")

        # Determine which pages to scan (0-based indices)
        start_idx = 0 if page_start is None else max(page_start - 1, 0)
        end_idx = n_pages - 1 if page_end is None else min(page_end - 1, n_pages - 1)
        if start_idx > end_idx:
            start_idx, end_idx = 0, n_pages - 1
        page_indices = range(start_idx, end_idx + 1)

        # Try to infer statement year from any 4-digit year on those pages
        statement_year = _infer_statement_year(pdf, page_indices)
        if statement_year is None:
            # Safe fallback; you can tweak if needed
            statement_year = 2025

        # Regex for a generic transaction row:
        #   MM/DD  ...  AMOUNT
        # where AMOUNT can be 23.93, -1,066.82, (123.45), $65.00, etc.
        tx_pattern = re.compile(
            r"^(\d{1,2}/\d{1,2})\s+(.+?)\s+(-?\(?\$?\d[\d,]*\.\d{2}\)?)$"
        )

        current_section: Optional[str] = None

        for idx in page_indices:
            page = pdf.pages[idx]
            text = page.extract_text() or ""
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

            for line in lines:
                # Optional: track sections if present
                if line.upper().startswith("PAYMENTS AND OTHER CREDITS"):
                    current_section = "Payments and Other Credits"
                    continue
                if line.upper().startswith("PURCHASE") and "ACCOUNT ACTIVITY" not in line.upper():
                    current_section = "Purchases"
                    continue
                if line.upper().startswith("FEES"):
                    current_section = "Fees"
                    continue
                if line.upper().startswith("INTEREST CHARGES"):
                    current_section = "Interest"
                    continue

                # Try to match transaction pattern
                m = tx_pattern.match(line)
                if not m:
                    continue

                mmdd, desc, amount_str = m.groups()

                # Build full date string using inferred year
                tran_date_str = f"{mmdd}/{statement_year}"

                records.append(
                    {
                        "transaction_date_str": tran_date_str,
                        "description": desc.strip(),
                        "amount_raw": amount_str.strip(),
                        "section": current_section,
                    }
                )

    if not records:
        raise ValueError(
            "No transaction-like lines found in PDF. "
            "If this is a very unusual statement layout, try entering a CSV/Excel export instead."
        )

    df = pd.DataFrame(records)

    # Convert date
    df["date"] = pd.to_datetime(
        df["transaction_date_str"], format="%m/%d/%Y", errors="coerce"
    )

    # Parse amount
    df["amount"] = df["amount_raw"].apply(_parse_amount)

    # Clean up
    df["description"] = df["description"].fillna("").astype(str).str.strip()
    df = df[df["amount"].notna()]
    df = df[df["date"].notna()]

    # Final column order
    cols = ["date", "description", "amount"]
    if "section" in df.columns:
        cols.append("section")

    return df[cols].reset_index(drop=True)


def _infer_statement_year(pdf: pdfplumber.PDF, page_indices) -> Optional[int]:
    """
    Generic year detector.

    We just look for any four-digit year like 2025 on the selected pages.
    This works for:
      - "December 2025" calendar on page 1 of your Chase PDF
      - "Opening/Closing Date 10/29/25 - 11/28/25" lines with "2025"
      - BoA headers like "November 6 - December 5, 2025"
    """
    year_pattern = re.compile(r"\b(20\d{2})\b")

    for idx in page_indices:
        page = pdf.pages[idx]
        text = page.extract_text() or ""
        m = year_pattern.search(text)
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


# ---------------------------------------------------------------------------
# Generic CSV/Excel cleaning (unchanged from v2)
# ---------------------------------------------------------------------------

def _standardize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """
    Standardize column names for CSV/Excel to match what we expect.

    Canonical names we use:
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

    df = df.rename(columns=col_map)

    # Drop duplicate columns, keeping first occurrence
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
