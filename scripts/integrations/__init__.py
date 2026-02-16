"""Integration clients for external systems (Notion, Linear, Sentry, Figma).

Loads `.env` and `~/.env` so integrations work consistently when imported directly.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_PROJECT_ROOT / ".env")
load_dotenv(Path.home() / ".env")
