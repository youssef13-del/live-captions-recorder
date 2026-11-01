@echo off
cd /d "%~dp0"
if exist "dist\LiveCaptionsRecorder.exe" (
    start "" "dist\LiveCaptionsRecorder.exe"
) else (
    py live_captions_to_txt.py
)
