@echo off
cd /d "%~dp0"
echo Starting DevAgent Studio at http://127.0.0.1:8100/
".venv\Scripts\python.exe" -m uvicorn app.main:app --reload --port 8100
