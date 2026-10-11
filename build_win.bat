@echo off
setlocal

REM Build do cliente THLPro para Windows 64-bit (Python 3.12)
python -m venv .venv
call .venv\Scriptsctivate
python -m pip install --upgrade pip
pip install -r requirements.txt
python build_client.py

echo.
echo Build finalizado. Verifique dist\THLProClient.exe
