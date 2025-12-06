#!/usr/bin/env bash

# 確保所有命令都成功執行
set -e

echo "--- Installing Python dependencies ---"
pip install -r requirements.txt

echo "--- Installing Playwright browsers using Node.js driver ---"
# 使用 Playwright 內建的 Node.js 驅動來執行安裝，更可靠
/opt/render/project/src/.venv/bin/playwright install --with-deps chromium
