"""Flask API for the SettleSense dashboard.

Serves pre-computed reconciliation data as JSON endpoints, plus the static
frontend files and the interactive AI Finance Controller Q&A and diagnostics.
"""

from __future__ import annotations

import json
import os
import sys

# Ensure src is in sys.path
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, jsonify, request, send_from_directory
from model import chat_controller, diagnose_exception, get_active_model_info

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")


def _load_json(filename: str) -> dict | list:
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def create_app() -> Flask:
    app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")

    # --- CORS Security & Cross-Origin Support ---------------------------------

    @app.after_request
    def add_cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return response

    # --- Health & Liveness Probe ----------------------------------------------

    @app.route("/health")
    def health():
        """Production health check endpoint for container probes and uptime monitors."""
        from datetime import datetime, timezone
        return jsonify({
            "status": "healthy",
            "service": "SettleSense AI Finance Controller",
            "version": "1.0.0",
            "model_info": get_active_model_info(),
            "datasets": {
                "dashboard_data": os.path.exists(os.path.join(DATA_DIR, "dashboard_data.json")),
                "metrics": os.path.exists(os.path.join(DATA_DIR, "metrics.json")),
                "tax_reconciliation": os.path.exists(os.path.join(DATA_DIR, "tax_reconciliation.json")),
                "gateway_settlement": os.path.exists(os.path.join(DATA_DIR, "gateway_settlement.csv")),
                "bank_statement": os.path.exists(os.path.join(DATA_DIR, "bank_statement.csv")),
                "internal_ledger": os.path.exists(os.path.join(DATA_DIR, "internal_ledger.csv")),
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    # --- Static frontend ------------------------------------------------------

    @app.route("/")
    def index():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.route("/<path:path>")
    def static_files(path):
        return send_from_directory(FRONTEND_DIR, path)

    # --- Model metadata -------------------------------------------------------

    @app.route("/api/model-info")
    def model_info():
        """Currently active LLM model and provider."""
        return jsonify(get_active_model_info())

    # --- API endpoints --------------------------------------------------------

    @app.route("/api/dashboard")
    def dashboard_data():
        """Full dashboard data bundle with active model metadata."""
        data = _load_json("dashboard_data.json")
        if isinstance(data, dict):
            data["model_info"] = get_active_model_info()
        return jsonify(data)

    @app.route("/api/metrics")
    def metrics():
        """Evaluation metrics."""
        data = _load_json("metrics.json")
        return jsonify(data)

    @app.route("/api/cash-position")
    def cash_position():
        """Cash position and forecast."""
        data = _load_json("cash_position.json")
        return jsonify(data)

    @app.route("/api/exceptions")
    def exceptions():
        """Exceptions list."""
        data = _load_json("dashboard_data.json")
        return jsonify(data.get("exceptions", []))

    @app.route("/api/audit/export")
    def audit_export():
        """Full audit trail as JSON or CSV."""
        fmt = request.args.get("format", "json")
        if fmt == "csv":
            csv_path = os.path.join(DATA_DIR, "audit_trail.csv")
            if os.path.exists(csv_path):
                return send_from_directory(DATA_DIR, "audit_trail.csv",
                                           mimetype="text/csv",
                                           as_attachment=True,
                                           download_name="audit_trail.csv")
        data = _load_json("audit_trail.json")
        return jsonify(data)

    @app.route("/api/audit/<trace_id>")
    def audit_record(trace_id):
        """Single audit trail record."""
        trail = _load_json("audit_trail.json")
        for record in trail:
            if record.get("trace_id") == trace_id:
                return jsonify(record)
        return jsonify({"error": "Not found"}), 404

    @app.route("/api/tax-reconciliation")
    def tax_reconciliation():
        """Monthly Razorpay Tax Invoice vs Fee Rollup vs GSTR-2B ITC reconciliation."""
        data = _load_json("tax_reconciliation.json")
        if not data:
            from tax_matcher import compute_tax_reconciliation
            data = compute_tax_reconciliation()
        return jsonify(data)

    @app.route("/api/tax/report")
    def tax_report():
        """Download complete GSTR-2B ITC reconciliation report."""
        data = _load_json("tax_reconciliation.json")
        if not data:
            from tax_matcher import compute_tax_reconciliation
            data = compute_tax_reconciliation()
        response = jsonify(data)
        response.headers["Content-Disposition"] = "attachment; filename=gstr2b_tax_reconciliation.json"
        return response

    @app.route("/api/cash-position/simulate", methods=["POST"])
    def cash_simulate():
        """Simulate cash position under settlement lag scenarios."""
        body = request.get_json() or {}
        lag_days = int(body.get("lag_days", 0))

        dashboard = _load_json("dashboard_data.json")
        # Load match results from audit trail if needed, or pass empty to compute from pending
        from cash_position import compute_cash_position
        # Reconstruct minimal results list
        from reconcile import MatchResult
        minimal_results = []
        for a in dashboard.get("audit_trail", []):
            minimal_results.append(MatchResult(
                trace_id=a["trace_id"],
                layer=a.get("layer", "exact"),
                bank_date=None,
                bank_narration="",
                bank_amount=float(a.get("bank_amount", 0.0) or 0.0),
                bank_utr=None,
                gateway_order_ids=[], gateway_payment_ids=[], gateway_utrs=[],
                gateway_net_amounts=[], gateway_total_net=None,
                ledger_order_ids=[], ledger_expected_amounts=[],
                amount_diff=None, confidence=None,
                status=a.get("status", "matched"),
                reason_code=None, reason="", suggested_step="",
            ))

        simulated = compute_cash_position(minimal_results, lag_days=lag_days)
        return jsonify(simulated)

    @app.route("/api/pipeline/rerun", methods=["POST"])
    def pipeline_rerun():
        """Trigger a live re-reconciliation run from the dashboard."""
        from main import run_pipeline
        updated_bundle = run_pipeline(skip_generate=True)
        return jsonify({
            "status": "success",
            "message": "Pipeline re-run completed successfully",
            "summary": updated_bundle.get("summary", {}),
        })

    # --- Interactive AI Controller Endpoints -----------------------------------

    @app.route("/api/chat", methods=["POST"])
    def chat():
        """Interactive Settlement & Finance Controller Q&A agent."""
        body = request.get_json() or {}
        message = body.get("message", "").strip()
        history = body.get("history", [])

        if not message:
            return jsonify({"error": "Empty message"}), 400

        dashboard = _load_json("dashboard_data.json")
        response_text = chat_controller(message, history, dashboard)

        return jsonify({
            "response": response_text,
            "model_info": get_active_model_info(),
        })

    @app.route("/api/agent/diagnose", methods=["POST"])
    def diagnose():
        """Deep AI root-cause analysis and merchant dispute drafting for an exception."""
        body = request.get_json() or {}
        trace_id = body.get("trace_id", "")

        dashboard = _load_json("dashboard_data.json")
        audit_trail = dashboard.get("audit_trail", [])

        target_record = None
        for r in audit_trail:
            if r.get("trace_id") == trace_id:
                target_record = r
                break

        if not target_record:
            return jsonify({"error": f"Record {trace_id} not found"}), 404

        diagnosis_text = diagnose_exception(target_record)

        return jsonify({
            "trace_id": trace_id,
            "diagnosis": diagnosis_text,
            "record": target_record,
            "model_info": get_active_model_info(),
        })

    return app


# Module-level WSGI instance for production servers (gunicorn, waitress)
app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "0.0.0.0")
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    print(f"Starting SettleSense production server on http://{host}:{port} (debug={debug})")
    app.run(host=host, port=port, debug=debug)
