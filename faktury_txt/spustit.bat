@echo off
REM Spustenie aplikacie Faktury PDF -> TXT (vyzaduje Python 3.10+ z python.org)
cd /d "%~dp0"
python -m pip install --quiet -r requirements.txt
start "" pythonw app.py %*
