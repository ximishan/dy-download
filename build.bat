@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d %~dp0

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] 构建机未检测到 Python 3.11+。
  pause
  exit /b 1
)

where git >nul 2>nul
if errorlevel 1 (
  echo [ERROR] 构建机未检测到 Git。Git 只在打包阶段需要，最终 EXE 不需要。
  pause
  exit /b 1
)

echo [1/6] 安装构建依赖...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :fail

if not exist vendor mkdir vendor
if not exist vendor\douyin-downloader\run.py (
  echo [2/6] 拉取上游下载核心...
  git clone --depth 1 https://github.com/jiji262/douyin-downloader.git vendor\douyin-downloader
  if errorlevel 1 goto :fail
) else (
  echo [2/6] 更新上游下载核心...
  git -C vendor\douyin-downloader pull --ff-only
  if errorlevel 1 goto :fail
)

python -m pip install -r vendor\douyin-downloader\requirements.txt
if errorlevel 1 goto :fail

echo [3/6] 下载并固定 Playwright Chromium...
set PLAYWRIGHT_BROWSERS_PATH=%CD%\ms-playwright
if exist ms-playwright rmdir /s /q ms-playwright
python -m playwright install chromium
if errorlevel 1 goto :fail

echo [4/6] 语法检查...
python -m py_compile launcher.py app.py backend.py bootstrap_backend.py scan_profile.py safe_download.py gui_cookie_login.py
if errorlevel 1 goto :fail

echo [5/6] 清理旧构建...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [6/6] 构建独立 Windows 发行版...
python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --onedir ^
  --name dy-download ^
  --paths "vendor\douyin-downloader" ^
  --collect-all PySide6 ^
  --collect-all playwright ^
  --collect-all aiohttp ^
  --collect-all httpx ^
  --collect-all rich ^
  --collect-all imageio_ffmpeg ^
  --collect-submodules core ^
  --collect-submodules cli ^
  --collect-submodules auth ^
  --collect-submodules control ^
  --collect-submodules tools ^
  --collect-submodules utils ^
  --collect-submodules database ^
  --hidden-import yaml ^
  --hidden-import aiosqlite ^
  --hidden-import aiofiles ^
  --hidden-import dateutil ^
  --hidden-import gmssl ^
  --hidden-import gui_cookie_login ^
  --add-data "vendor\douyin-downloader;vendor\douyin-downloader" ^
  --add-data "ms-playwright;ms-playwright" ^
  launcher.py
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo 构建完成
echo 发行目录：dist\dy-download\
echo 主程序：dist\dy-download\dy-download.exe
echo.
echo 最终用户无需安装 Python、Git、Playwright 或 Chromium。
echo 请分发整个 dist\dy-download 目录，不要只复制单独 EXE。
echo ============================================================
pause
exit /b 0

:fail
echo.
echo [ERROR] 构建失败，请查看上方日志。
pause
exit /b 1
