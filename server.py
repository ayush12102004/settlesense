"""Production server runner for SettleSense using Waitress (universal WSGI server).

Usage:
  python server.py
"""

import os
import sys

# Ensure root directory is in sys.path
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from src.wsgi import app
import waitress

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"============================================================")
    print(f"  SettleSense — Autonomous AI Finance Controller (Production)")
    print(f"  WSGI Server: Waitress (Production Multi-Threaded)")
    print(f"  Listening on: http://{host}:{port}")
    print(f"  Health Check: http://{host}:{port}/health")
    print(f"============================================================")
    waitress.serve(app, host=host, port=port, threads=8)
