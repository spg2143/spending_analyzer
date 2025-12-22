# main.py

from pathlib import Path
from typing import Optional, List

import io
import os
import pandas as pd

from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db import init_db, Base, get_db
import backend.db as db
from backend.models.vendor_map import VendorMap  # ensures model is registered
from backend.repositories.vendor_map_repo import upsert_vendor_mapping, delete_vendor_mapping

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

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "20"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

app = FastAPI(
    title="Small Business Spend Analyzer",
    description="Upload a bank statement (CSV, Excel, PDF) and get a spending breakdown.",
    version="1.2.0",
)


# -------------------- Startup: DB init --------------------

@app.on_event("startup")
def _startup():
    ok = init_db()
    if ok:
        Base.metadata.create_all(bind=db.ENGINE)


# -------------------- Middleware --------------------

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


# -------------------- Pydantic models --------------------

class TransactionIn(BaseModel):
    date: Optional[str] = None
    description: Optional[str] = ""
    amount: Optional[float] = None


class ReanalyzeRequest(BaseModel):
    transactions: List[TransactionIn]


class VendorMapIn(BaseModel):
    vendor: str
    category: str


# -------------------- Endpoints --------------------

@app.post("/api/analyze")
async def analyze_statement(
    statement: UploadFile = File(...),
    page_start: Optional[int] = Form(None),
    page_end: Optional[int] = Form(None),
    db: Session = Depends(get_db),
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
        if len(file_bytes) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Max allowed is {MAX_UPLOAD_MB} MB.",
            )

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

    # IMPORTANT: pass db so vendor_map is used (highest precision)
    df = categorize_transactions(df, db=db)
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
async def reanalyze_statement(body: ReanalyzeRequest, db: Session = Depends(get_db)):
    """
    Re-run the analysis on user-edited / manually-entered transactions.
    Expects a JSON body with:
        { "transactions": [ { "date": "...", "description": "...", "amount": ... }, ... ] }
    """
    if not body.transactions:
        raise HTTPException(status_code=400, detail="No transactions provided.")

    raw = [t.dict() for t in body.transactions]
    df = pd.DataFrame(raw)

    df = _standardize_column_names(df)
    df = _clean_transaction_df(df)

    if df.empty:
        raise HTTPException(status_code=400, detail="No valid transactions after cleaning.")

    # IMPORTANT: pass db so vendor_map is used
    df = categorize_transactions(df, db=db)
    summary = build_category_summary(df)

    preview_records = df.head(15).to_dict(orient="records")
    all_records = df.to_dict(orient="records")

    payload = {
        "summary": summary,
        "preview": preview_records,
        "transactions": all_records,
    }
    return JSONResponse(content=jsonable_encoder(payload))


@app.post("/api/export/csv")
async def export_transactions_csv(payload: dict):
    """
    Expects: { "transactions": [ {date, description, amount, category?, direction?}, ... ] }
    Returns: CSV download
    """
    transactions = payload.get("transactions", [])
    if not isinstance(transactions, list) or len(transactions) == 0:
        raise HTTPException(status_code=400, detail="No transactions provided.")

    df = pd.DataFrame(transactions)

    preferred = ["date", "description", "amount", "direction", "category"]
    cols = [c for c in preferred if c in df.columns] + [c for c in df.columns if c not in preferred]
    df = df[cols]

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date.astype(str)

    buf = io.StringIO()
    df.to_csv(buf, index=False)
    buf.seek(0)

    filename = "transactions_export.csv"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(buf, media_type="text/csv", headers=headers)


# -------------------- Vendor map endpoints (Postgres) --------------------

@app.post("/api/vendor-map")
def save_vendor_map(body: VendorMapIn, db: Session = Depends(get_db)):
    """
    Save a persistent mapping: vendor -> category.
    Your categorizer will apply these BEFORE rules/ML.
    """
    try:
        upsert_vendor_mapping(db, vendor=body.vendor, category=body.category)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/vendor-map")
def remove_vendor_map(vendor: str, db: Session = Depends(get_db)):
    ok = delete_vendor_mapping(db, vendor=vendor)
    return {"ok": ok}
