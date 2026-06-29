"""
Core blueprint — status, filter options, raw-data table, CSV export,
and page routes (index, simulator).

Presentation concerns kept here:
  - Display column selection for raw-data and export-csv
  - bool → Yes/No serialization
  - errors list → comma-separated string
  - Response headers (Content-Disposition)
"""
from __future__ import annotations

import io

import pandas as pd
from flask import Blueprint, Response, jsonify, render_template, request

from backend.routes.deps    import analytics_svc
from backend.routes.helpers import default_range, parse_date, parse_csv, read_filters, resolve_range
from backend.storage        import available_dates
from backend.utils          import ist_today

bp = Blueprint("core", __name__)

# Columns shown in raw-data table
_DISPLAY_TABLE = ["time", "partner", "offerName", "goal", "revenue", "payout",
                  "valid", "partnerValid", "errors"]

# Columns included in CSV export (wider set)
_DISPLAY_CSV = ["time", "partner", "offerName", "goal", "revenue", "payout",
                "valid", "partnerValid", "errors", "country", "city", "currency"]


def _serialise_raw(df: pd.DataFrame) -> pd.DataFrame:
    """Apply presentation-layer transforms to a raw postback DataFrame slice."""
    if "errors" in df.columns:
        df["errors"] = df["errors"].apply(
            lambda v: ", ".join(v) if isinstance(v, list) and v else ""
        )
    for col in ("valid", "partnerValid"):
        if col in df.columns:
            df[col] = df[col].map({True: "Yes", False: "No"}).fillna("—")
    for col in ("revenue", "payout"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).round(4)
    return df.where(pd.notnull(df), None)


# ── Page routes ────────────────────────────────────────────────────────────────

@bp.route("/simulator")
def simulator():
    offer = request.args.get("offer", "")
    return render_template("simulator.html", offer=offer)


@bp.route("/")
def index():
    from backend.config import SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY
    dates      = available_dates()
    today      = ist_today()
    import datetime as dt
    min_date   = dates[0].isoformat() if dates else (today - dt.timedelta(days=30)).isoformat()
    max_date   = dates[-1].isoformat() if dates else today.isoformat()
    return render_template(
        "index.html",
        min_date=min_date,
        max_date=max_date,
        default_from=today.replace(day=1).isoformat(),
        default_to=today.isoformat(),
        supabase_url=SUPABASE_URL,
        supabase_key=SUPABASE_PUBLISHABLE_KEY,
    )


# ── API: status ────────────────────────────────────────────────────────────────

@bp.route("/api/status")
def api_status():
    return jsonify(analytics_svc().status())


# ── API: filters ───────────────────────────────────────────────────────────────

@bp.route("/api/filters")
def api_filters():
    from_date, to_date, partners, offers, _ = read_filters()
    return jsonify(analytics_svc().filters(from_date, to_date, partners, offers, []))


# ── API: raw data (paginated) ──────────────────────────────────────────────────

@bp.route("/api/raw-data")
def api_raw_data():
    from_date, to_date, partners, offers, goals = read_filters()
    from_date, to_date = resolve_range(from_date, to_date)

    page     = max(1, int(request.args.get("page", 1)))
    per_page = max(10, min(int(request.args.get("per_page", 100)), 1000))
    search   = request.args.get("search", "").strip()

    result = analytics_svc().raw_data(
        from_date, to_date, partners, offers, goals,
        search, page, per_page,
    )

    # Presentation: select display columns and serialise special types
    rows = result["rows"]
    if rows:
        page_df = pd.DataFrame(rows)
        cols    = [c for c in _DISPLAY_TABLE if c in page_df.columns]
        page_df = page_df[cols].copy()
        page_df = _serialise_raw(page_df)
        result["rows"] = page_df.to_dict(orient="records")

    return jsonify(
        rows=result["rows"],
        total=result["total"],
        page=result["page"],
        per_page=result["per_page"],
        pages=result["pages"],
    )


# ── API: export CSV ────────────────────────────────────────────────────────────

@bp.route("/api/export-csv")
def api_export_csv():
    from_date, to_date, partners, offers, goals = read_filters()
    from_date, to_date = resolve_range(from_date, to_date)
    search = request.args.get("search", "").strip()

    csv_content, filename = analytics_svc().export_csv(
        from_date, to_date, partners, offers, goals, search,
    )

    if not csv_content or csv_content == "\n":
        return Response("No data available.", mimetype="text/plain", status=204)

    # Presentation: restrict to display columns before writing CSV
    try:
        df   = pd.read_csv(io.StringIO(csv_content))
        cols = [c for c in _DISPLAY_CSV if c in df.columns]
        df   = df[cols]
        if "errors" in df.columns:
            df["errors"] = df["errors"].fillna("").astype(str)
        csv_content = df.to_csv(index=False)
    except Exception:
        pass  # fall through with original content

    return Response(
        csv_content,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
