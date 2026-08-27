@echo off
chcp 65001 >nul
cd /d %~dp0

where python >nul 2>nul
if errorlevel 1 (
  echo 未检测到 Python，请先安装 Python 3.10 或更高版本。
  pause
  exit /b 1
)

python -m pip install -r requirements.txt
if errorlevel 1 (
  echo GUI 依赖安装失败。
  pause
  exit /b 1
)

python app.py
