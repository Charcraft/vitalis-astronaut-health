@echo off
rem V.I.T.A.L.I.S. en la tablet Android (pantalla remota tactil por USB).
rem Requisitos: tablet con "Depuracion USB" activada y autorizada en esta PC.
cd /d "%~dp0"
python vitalis_tablet.py %*
if errorlevel 1 pause
