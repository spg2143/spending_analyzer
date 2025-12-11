# main.py
from pathlib import Path

from fastapi.encoders import jsonable_encoder
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from backend.services.statement_reader import (
    load_statement_from_upload,
    UnsupportedFileTypeError,
)
from backend.services.categorizer import categorize_transactions, build_category_summary

app = FastAPI(
    title="Small Business Spend Analyzer",
    description="Upload a bank statement (CSV, Excel, PDF) and get a spending breakdown.",
    version="1.0.0",
)

# Allow local frontend / any origin (you can restrict later)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static frontend (files live in backend/static)
static_dir = Path(__file__).parent / "backend" / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def serve_index():
    """Serve the main webpage."""
    index_path = static_dir / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=500, detail="index.html not found")
    return FileResponse(str(index_path))


@app.post("/api/analyze")
async def analyze_statement(statement: UploadFile = File(...)):
    """
    Accept a bank statement upload and return:
    - overall summary (totals)
    - category breakdown
    - lightweight optimization suggestions
    - preview of parsed transactions
    """
    try:
        file_bytes = await statement.read()
        df = load_statement_from_upload(statement.filename, file_bytes)
    except UnsupportedFileTypeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read statement: {e}",
        )

    if df is None or df.empty:
        raise HTTPException(status_code=400, detail="No transactions found in file.")

    # Add categories etc.
    df = categorize_transactions(df)
    summary = build_category_summary(df)

    # Preview: first 15 transactions
    preview_records = df.head(15).to_dict(orient="records")

    payload = {
        "summary": summary,
        "preview": preview_records,
    }

    # This converts pandas Timestamps, datetimes, etc. into JSON-safe types
    return JSONResponse(content=jsonable_encoder(payload))