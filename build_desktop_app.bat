@echo off
cd /d "%~dp0"
py -m pip install -r requirements.txt
py -m pip install pyinstaller
py -m PyInstaller --noconfirm --clean --onefile --windowed --name LiveCaptionsRecorder live_captions_to_txt.py
echo.
echo Built: dist\LiveCaptionsRecorder.exe
pause
