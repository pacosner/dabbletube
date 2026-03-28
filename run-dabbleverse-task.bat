@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%" >nul 2>&1

set "WSL_EXE=%SystemRoot%\System32\wsl.exe"
set "TASK_NAME=Dabbleverse"
set "LOG_PATH=/home/pacos/dabbletube/output/task.log"
set "RUNNER_PATH=/home/pacos/dabbletube/run-dabbleverse-task.sh"
set "WINDOWS_LOG_PATH=%SCRIPT_DIR%output\task.log"

if not exist "%SCRIPT_DIR%output" mkdir "%SCRIPT_DIR%output"

>>"%WINDOWS_LOG_PATH%" echo(
>>"%WINDOWS_LOG_PATH%" echo ==== %TASK_NAME% launcher started %DATE% %TIME% ====
>>"%WINDOWS_LOG_PATH%" echo Launching WSL runner: %RUNNER_PATH%

"%WSL_EXE%" bash -lc "TASK_NAME=\"%TASK_NAME%\" LOG_PATH=\"%LOG_PATH%\" bash \"%RUNNER_PATH%\""
set "EXIT_CODE=%ERRORLEVEL%"

>>"%WINDOWS_LOG_PATH%" echo ==== %TASK_NAME% launcher finished %DATE% %TIME% exit=%EXIT_CODE% ====

if not "%EXIT_CODE%"=="0" (
  echo Dabbleverse task failed with exit code %EXIT_CODE%.
  >>"%WINDOWS_LOG_PATH%" echo Dabbleverse task failed with exit code %EXIT_CODE%.
)

popd >nul 2>&1
exit /b %EXIT_CODE%
