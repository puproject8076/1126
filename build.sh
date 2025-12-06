#!/usr/bin/env bash

# 確保所有命令都成功執行
set -e

echo "--- Installing Python dependencies ---"
pip install -r requirements.txt

echo "--- Installing Playwright browsers ---"
# Render 需要這個步驟來下載 Chromium 核心
playwright install chromium