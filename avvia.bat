@echo off
cd /d "%~dp0"
echo Avvio Analisi Finanziaria su http://localhost:8507 ...
python -m streamlit run app.py --server.port 8507
pause
