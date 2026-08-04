#!/usr/bin/env bash
set -euo pipefail

echo "📦 Installing BoomBench dependencies..."

if ! command -v python3 >/dev/null 2>&1; then
  echo "❌ python3 not found. Please install Python 3 first."
  exit 1
fi

if ! command -v pip3 >/dev/null 2>&1; then
  echo "⚠️ pip3 not found, trying: python3 -m ensurepip --upgrade"
  python3 -m ensurepip --upgrade || true
fi

python3 -m pip install --upgrade pip
python3 -m pip install requests

echo "✅ Done. Dependencies installed."