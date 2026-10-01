#!/bin/zsh
set -e

project_directory="$(cd "$(dirname "$0")" && pwd)"
cd "$project_directory"
exec /usr/bin/env python3 app.py

