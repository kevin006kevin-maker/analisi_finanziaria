@echo off
setlocal
cd /d "%~dp0"
title Analisi Finanziaria - installazione e avvio
echo ============================================================
echo     ANALISI FINANZIARIA  -  installazione e avvio (un clic)
echo ============================================================
echo.
echo Questo file prepara tutto da solo la prima volta, poi avvia l'app.
echo Le volte successive fa partire l'app direttamente.
echo.

REM (1) Python presente e nel PATH?
where python >nul 2>nul
if errorlevel 1 goto :nopython

REM (2) Se la .venv esiste ma non funziona (es. copiata da un altro PC), la ricreo
if not exist ".venv\Scripts\python.exe" goto :makevenv
".venv\Scripts\python.exe" -c "import sys" >nul 2>nul
if not errorlevel 1 goto :havevenv
echo [!] Ambiente virtuale non valido, forse copiato da un altro PC: lo ricreo da zero.
rmdir /s /q ".venv"

:makevenv
if exist ".venv\Scripts\python.exe" goto :havevenv
echo [1/3] Creo l'ambiente isolato ".venv" ...
python -m venv ".venv"
if errorlevel 1 goto :venvfail

:havevenv
REM (3) Installo le librerie solo se non gia' fatto con successo
if exist ".venv\.deps_ok" goto :launch
echo [2/3] Installo le librerie. Serve internet; la prima volta puo' volerci qualche minuto...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :pipfail
type nul > ".venv\.deps_ok"

:launch
echo [3/3] Avvio l'app su http://localhost:8507
echo.
echo     Il browser si aprira' da solo. Per FERMARE l'app, chiudi questa finestra.
echo.
".venv\Scripts\python.exe" -m streamlit run app.py --server.port 8507
echo.
echo App terminata. Premi un tasto per chiudere questa finestra.
pause >nul
goto :eof

:nopython
echo [X] Python non risulta installato, oppure non e' nel PATH.
echo.
echo     1^) Apri nel browser:  https://www.python.org/downloads/
echo     2^) Installa Python 3.12 e SPUNTA la casella "Add python.exe to PATH".
echo     3^) Richiudi e rilancia questo file (installa.bat).
echo.
pause
goto :eof

:venvfail
echo [X] Non sono riuscito a creare l'ambiente virtuale.
echo     Verifica che Python 3.12 sia installato correttamente, poi riprova.
pause
goto :eof

:pipfail
echo [X] Errore durante l'installazione delle librerie.
echo     Di solito manca la connessione a internet: controllala e rilancia installa.bat.
pause
goto :eof
