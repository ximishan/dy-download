@echo off
chcp 65001 >nul
setlocal
cd /d %~dp0

where python >nul 2>nul
if errorlevel 1 (
  echo 未检测到 Python 3.10+。
  pause
  exit /b 1
)

python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 exit /b 1

rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul

python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --name dy-download ^
  --collect-all PySide6 ^
  --add-data "backend.py;." ^
  --add-data "bootstrap_backend.py;." ^
  --add-data "scan_profile.py;." ^
  app.py

if errorlevel 1 (
  echo 打包失败。
  pause
  exit /b 1
)

echo.
echo 打包完成：dist\dy-download\dy-download.exe
echo 注意：当前发行版仍需要系统安装 Python 和 Git，用于拉取/运行上游下载核心。
pause
