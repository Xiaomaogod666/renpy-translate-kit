@echo off
rem ---------------------------------------------------------------
rem  This file must stay ASCII-only.
rem  cmd.exe parses .bat files using the system ANSI codepage, so
rem  UTF-8 Chinese text here corrupts the command parser.
rem  Chinese explanations live in README.md and the usage doc
rem  (both are UTF-8 Markdown; read them in an editor, not here).
rem
rem  Note on escaping: any literal ( or ) printed by echo INSIDE an
rem  if/for block must be written ^( and ^). A bare ) closes the block
rem  early and the rest of the block runs unconditionally.
rem ---------------------------------------------------------------
chcp 65001 >nul
title RenPy Translation Kit - Setup
setlocal
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

set "KIT=%~dp0"
set "ENGINE=%KIT%..\projz_renpy_translation"
set "REPO=https://github.com/abse4411/projz_renpy_translation.git"
set "ZIPURL=https://codeload.github.com/abse4411/projz_renpy_translation/zip/refs/heads/devp"
set "FETCH=%KIT%fetch_engine.py"
set "FETCHPIP=%KIT%fetch_pip.py"
set "VENV=%ENGINE%\.venv"

rem  Overrides (optional):
rem    KIT_PYTHON       python.exe to build the environment with
rem    KIT_ENGINE_REPO  git URL of another engine clone (set
rem                     KIT_ENGINE_ZIP too if it is not on github.com)
rem    KIT_ENGINE_ZIP   direct zip URL, or a local .zip path
rem    KIT_PIP_INDEX    pip index URL (e.g. a local mirror)
if defined KIT_ENGINE_REPO set "REPO=%KIT_ENGINE_REPO%"
if defined KIT_ENGINE_ZIP set "ZIPURL=%KIT_ENGINE_ZIP%"
set "PIPOPT="
if defined KIT_PIP_INDEX set "PIPOPT=-i %KIT_PIP_INDEX%"

echo.
echo ================================================================
echo   RenPy Translation Kit - one-time setup
echo ================================================================
echo.
echo   This will:
echo     1. download the translation engine into ..\projz_renpy_translation
echo     2. create a Python virtual environment inside it
echo     3. install the engine's dependencies with pip
echo.
echo   Requires: Python 3.9-3.11 ^(see README^). git is optional:
echo   without it the engine is fetched as a zip over https instead.
echo.

rem ---- 1) python --------------------------------------------------
rem  Do this FIRST: the engine fallback download below needs an
rem  interpreter, and the venv needs one either way.
rem
rem  The engine pins PyQt5 5.15.9 / numpy 1.24.4 / pandas 2.0.3, which
rem  ship no wheels for Python 3.12+. Prefer 3.11, then 3.10, then 3.9.
rem
rem  The `if exist` guards are load-bearing: a machine whose cmd AutoRun
rem  hook prints anything (e.g. a chcp line) gets that text as the FIRST
rem  line captured by `for /f`, which would otherwise be mistaken for a
rem  path.
set "PYEXE="
if defined KIT_PYTHON set "PYEXE=%KIT_PYTHON%"
if not defined PYEXE (
  for %%v in (3.11 3.10 3.9) do (
    if not defined PYEXE (
      for /f "delims=" %%p in ('py -%%v -c "import sys; print(sys.executable)" 2^>nul') do (
        if not defined PYEXE if exist "%%p" set "PYEXE=%%p"
      )
    )
  )
)
if not defined PYEXE (
  for /f "delims=" %%p in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do (
    if not defined PYEXE if exist "%%p" set "PYEXE=%%p"
  )
)
if not defined PYEXE (
  for /f "delims=" %%p in ('where python 2^>nul') do (
    if not defined PYEXE if exist "%%p" (
      "%%p" -c "import sys" >nul 2>nul && set "PYEXE=%%p"
    )
  )
)
if not defined PYEXE (
  echo [ERROR] No Python 3 interpreter found.
  echo.
  echo   Install Python 3.11 from https://www.python.org/downloads/
  echo   ^(tick "Add python.exe to PATH" in the installer^) and run this
  echo   file again.
  echo.
  pause
  exit /b 1
)
echo [OK]   python: %PYEXE%
"%PYEXE%" -c "import sys; sys.exit(0 if sys.version_info[:2] <= (3, 11) else 1)"
if errorlevel 1 (
  echo [WARN] Python 3.12 or newer detected. The engine's pinned
  echo        dependencies have no prebuilt packages for it, so the
  echo        dependency install below will likely fail. Python 3.11
  echo        is the recommended version.
  echo.
)
"%PYEXE%" -c "import zipfile, urllib.request" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] This Python lacks the standard library modules needed to
  echo   download the engine zip -- it looks like a stripped build.
  echo   Use an official Python from python.org.
  echo.
  pause
  exit /b 1
)

rem ---- 2) engine --------------------------------------------------
if exist "%ENGINE%\main.py" (
  echo [OK]   engine already present:
  echo        %ENGINE%
) else (
  if exist "%ENGINE%" (
    echo [ERROR] %ENGINE%
    echo   exists but does not look like the engine ^(main.py missing^).
    echo   Move or delete that folder, then run this file again.
    echo.
    pause
    exit /b 1
  )
  set "GOT="

  where git >nul 2>nul
  if not errorlevel 1 (
    echo ...    cloning the engine ^(first time only^) ...
    git clone --depth 1 "%REPO%" "%ENGINE%"
    if not errorlevel 1 if exist "%ENGINE%\main.py" set "GOT=1"
    if not defined GOT (
      echo.
      echo [WARN] git clone failed -- falling back to a direct download ...
      if exist "%ENGINE%" rd /s /q "%ENGINE%" 2>nul
    )
  ) else (
    echo ...    git not found -- fetching the engine as a zip ...
  )

  if not defined GOT (
    "%PYEXE%" "%FETCH%" "%ENGINE%" "%ZIPURL%"
    if not errorlevel 1 set "GOT=1"
  )
  if not defined GOT (
    echo.
    echo [ERROR] Could not obtain the engine.
    echo.
    echo   Manual fallback: download
    echo     %ZIPURL%
    echo   as a .zip, then run
    echo     "%PYEXE%" "%FETCH%" "%ENGINE%" "path\to\engine.zip"
    echo.
    pause
    exit /b 1
  )
)

rem ---- 3) virtual environment -------------------------------------
if exist "%VENV%\Scripts\python.exe" (
  echo [OK]   virtual environment already present:
  echo        %VENV%
) else (
  echo ...    creating virtual environment ...
  "%PYEXE%" -m venv "%VENV%"
  if errorlevel 1 (
    echo.
    echo [ERROR] Could not create the virtual environment.
    echo.
    pause
    exit /b 1
  )
)

rem ---- 4) dependencies --------------------------------------------
echo ...    installing dependencies ^(this can take a few minutes^) ...

rem  A fresh venv carries the pip that shipped with its Python; for 3.11
rem  that is pip 23.x. On some networks -- corporate proxies that inspect
rem  TLS, or package mirrors with their own chain -- that old pip cannot
rem  verify HTTPS, and in that state it cannot upgrade itself either. So:
rem  try normally first, and only if that fails pay for the official
rem  bootstrap, which downloads with the standard library and installs
rem  pip from embedded wheels. Then retry the dependencies once.
set "DEPOK="
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip --disable-pip-version-check %PIPOPT% >nul 2>nul
"%VENV%\Scripts\python.exe" -m pip install -r "%ENGINE%\requirements.txt" --disable-pip-version-check %PIPOPT%
if not errorlevel 1 set "DEPOK=1"

if not defined DEPOK (
  echo.
  echo [WARN] Dependency installation failed -- repairing pip and retrying ...
  "%PYEXE%" "%FETCHPIP%" "%VENV%"
  if not errorlevel 1 (
    "%VENV%\Scripts\python.exe" -m pip install -r "%ENGINE%\requirements.txt" --disable-pip-version-check %PIPOPT%
    if not errorlevel 1 set "DEPOK=1"
  )
)

if not defined DEPOK (
  echo.
  echo [ERROR] Dependency installation failed. Read the pip output above.
  echo   A slow or blocked network is the usual cause. Options:
  echo     set KIT_PIP_INDEX=https://a-mirror/simple    then rerun this file
  echo   Or fetch the bootstrap by hand:
  echo     https://bootstrap.pypa.io/get-pip.py
  echo   and run
  echo     "%PYEXE%" "%FETCHPIP%" "%VENV%" "path\to\get-pip.py"
  echo.
  pause
  exit /b 1
)

rem ---- 5) verify --------------------------------------------------
pushd "%ENGINE%"
"%VENV%\Scripts\python.exe" -c "import sys, log; from command.manage import execute_cmd; from store import TranslationIndex; print('engine import ok on python', sys.version.split()[0])"
set "VERC=%ERRORLEVEL%"
popd
if not "%VERC%"=="0" (
  echo [ERROR] The engine does not import in the new environment.
  echo   Read the output above; a Python version mismatch ^(see the WARN
  echo   earlier^) is the usual cause.
  echo.
  pause
  exit /b 1
)

echo.
echo ================================================================
echo   Setup complete.
echo.
echo   Next: drag a game folder ^(the layer with the .exe^) onto the
echo         translate .bat file
echo ================================================================
echo.
pause
exit /b 0
