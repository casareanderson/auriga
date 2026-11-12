@echo off
REM Setup Auriga on Windows: create the config, then register the bridge as a
REM Task Scheduler autostart (ONLOGON) that launches pythonw.exe so it starts
REM with no console window. Runs per-user in the interactive logon session.
setlocal

set "HERE=%~dp0"

REM --- 1. Resolve an absolute path to pythonw.exe.
REM       Autostart MUST NOT rely on python/py being on PATH (the logon PATH may
REM       be reduced or reordered). Prefer `where pythonw.exe`, then locate the
REM       interpreter via the always-present py launcher, then per-user paths.
set "PYW="
for /f "delims=" %%i in ('where pythonw.exe 2^>nul') do if not defined PYW set "PYW=%%i"
if defined PYW goto :havepyw
for /f "delims=" %%i in ('py -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))" 2^>nul') do if not defined PYW set "PYW=%%i"
if defined PYW goto :havepyw
for %%p in ("%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe" "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe" "%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe") do if exist %%p if not defined PYW set "PYW=%%~p"
if not defined PYW goto :nofound
:havepyw
if not exist "%PYW%" goto :nofound
echo pythonw  =  %PYW%

REM --- 2. Create the config file (idempotent — will not overwrite an existing
REM       config, e.g. one with a token/ephor setup already in place). Mirrors
REM       the defaults install.sh writes.
if not exist "%USERPROFILE%\.auriga" mkdir "%USERPROFILE%\.auriga"
%PYW% -c "import os,json;p=os.path.expanduser('~/.auriga/config.json');os.makedirs(os.path.dirname(p),exist_ok=True);d={'port':8765,'agent':'auriga','ephor_url':'','ephor_token':'','webhook_url':'','session_max_min':0};open(p,'w').write(json.dumps(d,indent=2)) if not os.path.exists(p) else None"
echo Config  =  %USERPROFILE%\.auriga\config.json

REM --- 3. Register the bridge as a Task Scheduler task that runs at logon in
REM       the interactive session as the current user (no elevation, no /RU
REM       SYSTEM, no "run whether logged on or not"), with a 30s delay so
REM       Explorer/Chrome settle before it binds the port.
schtasks /Create /TN AurigaBridge /SC ONLOGON /DELAY 0000:30 /F /TR "cmd /c \"%PYW%\" \"%HERE%auriga.py\" >> \"%USERPROFILE%\.auriga\bridge.log\" 2>&1" >nul
if errorlevel 1 ( echo ERROR: failed to register the autostart task. & exit /b 1 )
echo Autostart  =  AurigaBridge (Task Scheduler, runs at logon)

REM --- 4. Start the bridge now.
schtasks /Run /TN AurigaBridge >nul

echo.
echo Setup done — the bridge is starting in the background.
echo.
echo Last step, load the extension:
echo   chrome://extensions  -  Developer mode  -  Load unpacked  -  %HERE%extension
echo.
echo Then it just works, e.g.   auriga.bat tabs
echo Other:  auriga.bat status - auriga.bat stop
echo Uninstall:  schtasks /End /TN AurigaBridge  then  schtasks /Delete /TN AurigaBridge /F
exit /b 0

:nofound
echo ERROR: Python not found. Install Python from https://www.python.org/downloads/
echo (tick "Add Python to PATH" and "Install the py launcher"), then re-run.
exit /b 1
