#!/bin/bash
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required. Install it from https://www.python.org/downloads/ and run again."
  read -n 1
  exit 1
fi
exec python3 app.py
