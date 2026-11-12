@echo off
REM CLI wrapper for the auriga Python script.
REM %~dp0 points at the folder containing this file; the script has no
REM extension, so it must be handed to python explicitly on Windows.
@python "%~dp0auriga" %*
