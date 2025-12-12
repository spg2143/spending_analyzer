from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel

import pandas as pd

from backend.services.statement_reader import (
    load_statement_from_upload,
    UnsupportedFileTypeError,
    _standardize_column_names,
    _clean_transaction_df,
)
from backend.services.categorizer import (
    categorize_transactions,
    build_category_summary,
)

app = FastAPI(
    title="Small Business Spend Analyzer",
    description="Upload a bank statement (CSV, Excel, PDF) and get a spending breakdown.",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the bundled frontend assets under /static
static_dir = Path(__file__).parent / "backend" / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def serve_index():
    index_path = static_dir / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=500, detail="index.html not found")
    return FileResponse(str(index_path))


# ---------- Models for manual re-analysis ----------

class TransactionIn(BaseModel):
    date: Optional[str] = None
    description: Optional[str] = ""
    amount: Optional[float] = None


class ReanalyzeRequest(BaseModel):
    transactions: List[TransactionIn]


# ---------- Endpoints ----------

@app.post("/api/analyze")
async def analyze_statement(
    statement: UploadFile = File(...),
    page_start: Optional[int] = Form(None),
    page_end: Optional[int] = Form(None),
):
    """
    Accept a bank statement upload and return:
        - overall summary
        - category breakdown
        - optimization suggestions
        - preview and full transaction list

    Optional:
        page_start / page_end (1-based) for PDFs to restrict which pages are scanned.
    """
    try:
        file_bytes = await statement.read()
        df = load_statement_from_upload(
            statement.filename,
            file_bytes,
            page_start=page_start,
            page_end=page_end,
        )
    except UnsupportedFileTypeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read statement: {e}")

    if df is None or df.empty:
        raise HTTPException(status_code=400, detail="No transactions found in file.")

    df = categorize_transactions(df)
    summary = build_category_summary(df)

    preview_records = df.head(15).to_dict(orient="records")
    all_records = df.to_dict(orient="records")

    payload = {
        "summary": summary,
        "preview": preview_records,
        "transactions": all_records,
    }
    return JSONResponse(content=jsonable_encoder(payload))


@app.post("/api/reanalyze")
async def reanalyze_statement(body: ReanalyzeRequest):
    """
    Re-run the analysis on user-edited / manually-entered transactions.
    Expects a JSON body with:
        { "transactions": [ { "date": "...", "description": "...", "amount": ... }, ... ] }
    """
    if not body.transactions:
        raise HTTPException(status_code=400, detail="No transactions provided.")

    # Build DataFrame from incoming rows
    raw = [t.dict() for t in body.transactions]
    df = pd.DataFrame(raw)

    # Standardize & clean like a generic CSV
    df = _standardize_column_names(df)
    df = _clean_transaction_df(df)

    if df.empty:
        raise HTTPException(status_code=400, detail="No valid transactions after cleaning.")

    df = categorize_transactions(df)
    summary = build_category_summary(df)

    preview_records = df.head(15).to_dict(orient="records")
    all_records = df.to_dict(orient="records")

    payload = {
        "summary": summary,
        "preview": preview_records,
        "transactions": all_records,
    }
    return JSONResponse(content=jsonable_encoder(payload))
