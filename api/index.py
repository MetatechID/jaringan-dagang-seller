"""Vercel serverless entry point for the BPP (seller) FastAPI backend."""

import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

_main = __import__("app.main", fromlist=["app"])
app = _main.app
