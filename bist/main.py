from typing import Any
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

app = FastAPI(title="BIST TradingView Scanner")

BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

TRADINGVIEW_URL = "https://scanner.tradingview.com/turkey/scan?label-product=screener-stock"
DEFAULT_COLUMNS = [
    "name",
    "close",
    "price_earnings_ttm",
    "dividend_yield_recent",
    "market_cap_basic",
    "debt_to_equity",
    "price_book_ratio",
    "return_on_equity",
    "sector",
]


class ScanRequest(BaseModel):
    pe_max: float = Field(default=8.0, ge=0)
    dividend_min: float = Field(default=8.0, ge=0)
    market_cap_min: float = Field(default=5_000_000_000, ge=0)
    limit: int = Field(default=20, ge=1, le=200)


def build_payload(params: ScanRequest) -> dict[str, Any]:
    return {
        "columns": DEFAULT_COLUMNS,
        "sort": {"sortBy": "dividend_yield_recent", "sortOrder": "desc"},
        "range": [0, params.limit],
        "markets": ["turkey"],
        "options": {"lang": "en"},
        "filter2": {
            "operator": "and",
            "operands": [
                {
                    "operation": {
                        "operator": "and",
                        "operands": [
                            {
                                "expression": {
                                    "left": "type",
                                    "operation": "equal",
                                    "right": "stock",
                                }
                            },
                            {
                                "expression": {
                                    "left": "typespecs",
                                    "operation": "has",
                                    "right": ["common"],
                                }
                            },
                            {
                                "expression": {
                                    "left": "typespecs",
                                    "operation": "has_none_of",
                                    "right": ["pre-ipo"],
                                }
                            },
                        ],
                    }
                },
                {
                    "expression": {
                        "left": "price_earnings_ttm",
                        "operation": "in_range",
                        "right": [0, params.pe_max],
                    }
                },
                {
                    "expression": {
                        "left": "dividend_yield_recent",
                        "operation": "egreater",
                        "right": params.dividend_min,
                    }
                },
                {
                    "expression": {
                        "left": "market_cap_basic",
                        "operation": "egreater",
                        "right": params.market_cap_min,
                    }
                },
            ],
        },
    }


def row_to_dict(symbol: str, values: list[Any]) -> dict[str, Any]:
    row = {"symbol": symbol}
    for idx, col in enumerate(DEFAULT_COLUMNS):
        row[col] = values[idx] if idx < len(values) else None
    return row


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/scan")
async def scan_stocks(scan_request: ScanRequest) -> dict[str, Any]:
    payload = build_payload(scan_request)
    headers = {
        "content-type": "application/json",
        "origin": "https://www.tradingview.com",
        "referer": "https://www.tradingview.com/",
        "user-agent": "Mozilla/5.0",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(TRADINGVIEW_URL, headers=headers, json=payload)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"TradingView request failed: {exc}") from exc

    data = response.json()
    rows = [
        row_to_dict(item.get("s", ""), item.get("d", []))
        for item in data.get("data", [])
    ]

    return {
        "totalCount": data.get("totalCount", len(rows)),
        "returnedCount": len(rows),
        "rows": rows,
        "columns": DEFAULT_COLUMNS,
    }
