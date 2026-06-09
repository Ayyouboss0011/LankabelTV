#!/usr/bin/env bash
# Run the LankabelTV E2E test suite.
#
# This script:
# 1. Verifies Playwright chromium is installed
# 2. Starts a Docker container with the latest build of LankabelTV
# 3. Runs the pytest suite
# 4. Cleans up
#
# Usage:
#   tests/e2e/run.sh           # run all tests
#   tests/e2e/run.sh test_03   # run a specific test file

set -euo pipefail

cd "$(dirname "$0")/../.."

echo "==> Checking prerequisites..."
if ! command -v docker &> /dev/null; then
    echo "ERROR: docker is not installed"
    exit 1
fi

if ! /opt/miniconda3/bin/python -c "import playwright" &> /dev/null 2>&1; then
    echo "Installing playwright (run in miniconda)..."
    /opt/miniconda3/bin/pip install -q playwright pytest pytest-asyncio
fi

if [ ! -d "$HOME/Library/Caches/ms-playwright/chromium-1208" ] && [ ! -d "$HOME/Library/Caches/ms-playwright/chromium-1217" ] && [ ! -d "$HOME/Library/Caches/ms-playwright/chromium-1223" ]; then
    echo "Installing chromium for playwright..."
    PLAYWRIGHT_BROWSERS_PATH="$HOME/Library/Caches/ms-playwright" /opt/miniconda3/bin/playwright install chromium
fi

echo "==> Building docker image (cached if already built)..."
docker build -t lankabeltv-e2e-test . 2>&1 | tail -3

echo "==> Running tests..."
PYTHONPATH=. /opt/miniconda3/bin/pytest tests/e2e/ -v -x "${@:-}" 2>&1

echo "==> Done."
