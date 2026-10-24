@echo off
cd /d "%~dp0"
set "DSH_HOME=%~dp0data"
if exist "%USERPROFILE%\.dsh\electron\electron.exe" set "DSH_PET_ELECTRON_PATH=%USERPROFILE%\.dsh\electron\electron.exe"
node runtime\lib\standalone.js
pause
