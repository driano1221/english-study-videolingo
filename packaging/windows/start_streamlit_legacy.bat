@echo off
chcp 65001 >nul
setlocal

for %%I in ("%~dp0..\..") do set "REPO_DIR=%%~fI"
for %%I in ("%REPO_DIR%\..") do set "WORKSPACE_DIR=%%~fI"
cd /d "%REPO_DIR%"

set "PATH=%WORKSPACE_DIR%\tools\ffmpeg\bin;%PATH%"
set "HF_HUB_DISABLE_SYMLINKS=1"
set "PYTHONIOENCODING=utf-8"

start "VideoLingo" "%REPO_DIR%\.venv\Scripts\streamlit.exe" run st.py

echo VideoLingo esta iniciando no navegador...
echo Aguarde alguns segundos e acesse: http://localhost:8501
pause
