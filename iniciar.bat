@echo off
rem Sobe o painel e abre o navegador. Feche esta janela para parar o servidor.
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
  echo Python nao encontrado. Instale em https://python.org e marque
  echo "Add Python to PATH" durante a instalacao.
  pause
  exit /b 1
)

python -c "import flask, requests" >nul 2>&1
if errorlevel 1 (
  echo Instalando dependencias...
  python -m pip install -r requirements.txt
)

python app.py %*
pause
