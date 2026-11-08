@echo off
cd /d "%~dp0"
python demo\prepare_demo.py
if errorlevel 1 exit /b 1
echo Open http://127.0.0.1:8766 - SYNTHETIC DEMO, rule outputs only.
python server.py --port 8766 --db data\public_demo.sqlite
