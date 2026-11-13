@echo off
rem Double-click this file to start Analog Atlas WITHOUT the 3D globe (?no3d), for a demo with no internet.
rem Everything else works offline: rankings, Twin view, photos, Discover Jordan. Use start.bat when online.
setlocal
cd /d "%~dp0"
rem Pick Python once, so a failed start (for example port 8080 already in use) does not run twice.
set "PY="
python -c "import http.server as h; h.ThreadingHTTPServer" >nul 2>nul && set "PY=python"
if not defined PY (py -c "import http.server as h; h.ThreadingHTTPServer" >nul 2>nul && set "PY=py")
if not defined PY (
  echo Python 3 was not found. Install it from https://www.python.org/downloads/ and run this file again.
  pause
  exit /b 1
)
echo Starting Analog Atlas (offline, no 3D globe) on http://localhost:8080/?no3d ...
%PY% serve.py --open --offline --quiet
pause
