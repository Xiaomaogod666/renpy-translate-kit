@echo off
rem ---------------------------------------------------------------
rem  This file must stay ASCII-only.
rem  cmd.exe parses .bat files using the system ANSI codepage, so
rem  UTF-8 Chinese text here corrupts the command parser. All
rem  Chinese messages are printed by kit.py instead.
rem ---------------------------------------------------------------
chcp 65001 >nul
title RenPy Translation Kit
setlocal
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

set "KIT=%~dp0"
set "ENGINE=%KIT%..\projz_renpy_translation"
set "PY="

rem ---- locate a Python interpreter (see the setup .bat) ------------
rem   1) %KIT_PYTHON% if set   2) engine venv   3) kit venv   4) PATH
if defined KIT_PYTHON set "PY=%KIT_PYTHON%"
if not defined PY if exist "%ENGINE%\.venv\Scripts\python.exe" set "PY=%ENGINE%\.venv\Scripts\python.exe"
if not defined PY if exist "%KIT%.venv\Scripts\python.exe" set "PY=%KIT%.venv\Scripts\python.exe"
if not defined PY (
  for /f "delims=" %%p in ('where python 2^>nul') do (
    if not defined PY (
      "%%p" -c "import sys" >nul 2>nul && set "PY=%%p"
    )
  )
)

if not defined PY (
  echo.
  echo [ERROR] No Python environment found.
  echo.
  echo   Run the setup .bat in this folder first -- it downloads the engine
  echo   and installs everything into
  echo     %ENGINE%\.venv
  echo.
  echo   Or set KIT_PYTHON to an existing python.exe.
  echo.
  pause
  exit /b 1
)

if "%~1"=="" (
  "%PY%" "%KIT%kit.py"
  echo.
  pause
  exit /b 0
)

"%PY%" "%KIT%kit.py" %*
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
  echo [DONE] Failed. See the messages above.
) else (
  echo [DONE] Press any key to close.
)
pause >nul
exit /b %RC%
