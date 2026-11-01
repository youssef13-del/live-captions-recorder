# Live Captions Recorder

Windows desktop app that reads Windows Live Captions, displays the transcript
live, and saves it to a UTF-8 `.txt` file.

## Run

Double-click `Start Live Captions Recorder.bat`, or run:

```powershell
py .\live_captions_to_txt.py
```

Click **Start Live Captions**, choose the output file, and click **Stop and
save** when finished. The app flushes the file continuously while recording.

## Build

Run `build_desktop_app.bat` to create:

```powershell
dist\LiveCaptionsRecorder.exe
```

Windows Live Captions must be available under **Settings > Accessibility >
Captions**. The app identifies the source by its Windows
`LiveCaptionsDesktopWindow` class and never reads unrelated windows.
