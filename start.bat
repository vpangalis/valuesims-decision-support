@echo off
call .venv\Scripts\activate
uvicorn backend.app:app --reload --port 8010 --log-level info --reload-exclude "logs/*"
pause
