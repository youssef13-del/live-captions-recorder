"""Save Windows Live Captions to a text file.

Windows Live Captions does not provide a documented text-export API. This tool
uses the captions window's Windows UI Automation text, which avoids OCR and
preserves the text exposed by the operating system.
"""

from __future__ import annotations

import argparse
import ctypes
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Iterable, cast

VK_L = 0x4C
VK_LWIN = 0x5B
VK_CONTROL = 0x11
KEYEVENTF_KEYUP = 0x0002


def press_live_captions_hotkey() -> None:
    """Toggle Live Captions with the Windows shortcut Win+Ctrl+L."""
    keybd_event = ctypes.windll.user32.keybd_event
    keybd_event(VK_LWIN, 0, 0, 0)
    keybd_event(VK_CONTROL, 0, 0, 0)
    keybd_event(VK_L, 0, 0, 0)
    keybd_event(VK_L, 0, KEYEVENTF_KEYUP, 0)
    keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
    keybd_event(VK_LWIN, 0, KEYEVENTF_KEYUP, 0)


def find_captions_window():
    """Return the Live Captions UI Automation window."""
    from pywinauto import Desktop

    desktop = Desktop(backend="uia")
    windows = desktop.windows(class_name="LiveCaptionsDesktopWindow")
    if windows:
        return windows[0]

    raise RuntimeError(
        "The Windows Live Captions window was not found. Enable Live Captions "
        "with Ctrl+Win+L and try again."
    )


def ensure_captions_window(timeout: float = 10.0):
    """Start or toggle Windows Live Captions until its UI window is available."""
    try:
        return find_captions_window()
    except RuntimeError:
        pass

    press_live_captions_hotkey()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return find_captions_window()
        except RuntimeError:
            time.sleep(0.25)

    subprocess.Popen(
        [r"C:\Windows\System32\LiveCaptions.exe"],
        close_fds=True,
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return find_captions_window()
        except RuntimeError:
            time.sleep(0.25)
    raise RuntimeError(
        "Windows Live Captions could not be started. Enable it in "
        "Settings > Accessibility > Captions."
    )


def read_caption_lines(window) -> list[str]:
    """Read non-empty text controls currently exposed by the captions window."""
    lines: list[str] = []
    for control in window.descendants(control_type="Text"):
        text = control.window_text().strip()
        if text and text not in lines:
            lines.append(text)
    return lines


def new_lines(previous: Iterable[str], current: Iterable[str]) -> list[str]:
    """Return the current caption lines that were not already written."""
    previous_set = set(previous)
    return [line for line in current if line not in previous_set]


def record(
    output: Path,
    poll_interval: float,
    timeout: float,
    stop_event: threading.Event | None = None,
    on_lines: Callable[[list[str]], None] | None = None,
) -> None:
    """Poll the captions window, append new lines, and optionally publish them."""
    started = time.monotonic()
    window = None
    while window is None:
        try:
            window = find_captions_window()
        except RuntimeError:
            if time.monotonic() - started >= timeout:
                raise
            time.sleep(0.25)

    output.parent.mkdir(parents=True, exist_ok=True)
    previous: list[str] = []
    with output.open("a", encoding="utf-8", newline="\n") as file:
        while stop_event is None or not stop_event.is_set():
            current = read_caption_lines(window)
            added = new_lines(previous, current)
            for line in added:
                file.write(line + "\n")
                file.flush()
            if added and on_lines is not None:
                on_lines(added)
            previous = current
            time.sleep(poll_interval)


class LiveCaptionsApp:
    """Desktop interface for toggling and recording Windows Live Captions."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Live Captions Recorder")
        self.root.geometry("760x560")
        self.root.minsize(620, 420)

        self.output_path = tk.StringVar(value=str(Path("live_captions.txt").resolve()))
        self.status = tk.StringVar(value="Ready")
        self.elapsed = tk.StringVar(value="00:00:00")
        self.line_count = tk.StringVar(value="0 lines")
        self.file_state = tk.StringVar(value="Not recording")
        self.is_recording = False
        self.started_at = 0.0
        self.total_lines = 0
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()

        self._build_ui()
        self.root.after(100, self._process_events)
        self.root.after(1000, self._update_elapsed)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _build_ui(self) -> None:
        style = ttk.Style()
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("Subtitle.TLabel", foreground="#64748b")
        style.configure("Status.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(3, weight=1)

        header = ttk.Frame(self.root, padding=(20, 18, 20, 8))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Live Captions Recorder", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            text="Capture Windows Live Captions and save them automatically",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, pady=(3, 0), sticky="w")

        controls = ttk.LabelFrame(self.root, text="Recording setup", padding=12)
        controls.grid(row=1, column=0, padx=20, pady=(0, 8), sticky="ew")
        controls.columnconfigure(1, weight=1)

        ttk.Label(controls, text="Save transcript to:").grid(
            row=0, column=0, padx=(0, 8), pady=4, sticky="w"
        )
        ttk.Entry(controls, textvariable=self.output_path).grid(
            row=0, column=1, pady=4, sticky="ew"
        )
        self.browse_button = ttk.Button(
            controls, text="Browse...", command=self._browse_output
        )
        self.browse_button.grid(row=0, column=2, padx=(8, 0), pady=4)

        actions = ttk.Frame(self.root, padding=(20, 0, 20, 12))
        actions.grid(row=2, column=0, sticky="ew")
        actions.columnconfigure(3, weight=1)
        self.toggle_button = ttk.Button(
            actions,
            text="Start Live Captions",
            command=self._toggle_recording,
            style="Accent.TButton",
        )
        self.toggle_button.pack(side="left")
        self.clear_button = ttk.Button(
            actions, text="Clear transcript", command=self._clear_transcript
        )
        self.clear_button.pack(side="left", padx=(8, 0))
        ttk.Label(actions, textvariable=self.status, style="Status.TLabel").pack(
            side="left", padx=14
        )
        ttk.Label(actions, textvariable=self.elapsed).pack(side="right")

        transcript_frame = ttk.LabelFrame(
            self.root, text="Live transcript", padding=8
        )
        transcript_frame.grid(row=3, column=0, padx=20, pady=(0, 12), sticky="nsew")
        transcript_frame.columnconfigure(0, weight=1)
        transcript_frame.rowconfigure(0, weight=1)
        self.transcript = tk.Text(
            transcript_frame,
            wrap="word",
            state="disabled",
            background="#111827",
            foreground="#f9fafb",
            insertbackground="#f9fafb",
            padx=10,
            pady=10,
        )
        self.transcript.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(
            transcript_frame, orient="vertical", command=self.transcript.yview
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.transcript.configure(yscrollcommand=scrollbar.set)
        footer = ttk.Frame(self.root, padding=(20, 0, 20, 14))
        footer.grid(row=4, column=0, sticky="ew")
        ttk.Label(footer, textvariable=self.file_state, style="Subtitle.TLabel").pack(
            side="left"
        )
        ttk.Label(footer, textvariable=self.line_count, style="Subtitle.TLabel").pack(
            side="right"
        )

    def _browse_output(self) -> None:
        selected = filedialog.asksaveasfilename(
            title="Save transcript",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialfile=Path(self.output_path.get()).name,
        )
        if selected:
            self.output_path.set(selected)

    def _toggle_recording(self) -> None:
        if self.is_recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self) -> None:
        output = Path(self.output_path.get().strip())
        if not output.name:
            messagebox.showerror("Missing file", "Choose a transcript file first.")
            return

        self.is_recording = True
        self.started_at = time.monotonic()
        self.stop_event.clear()
        self.toggle_button.configure(text="Stop and save")
        self.browse_button.configure(state="disabled")
        self.clear_button.configure(state="disabled")
        self.status.set("Waiting for Live Captions...")
        self.file_state.set(f"Saving to {output}")
        self.worker = threading.Thread(
            target=self._capture_worker,
            args=(output,),
            daemon=True,
        )
        self.worker.start()

    def _capture_worker(self, output: Path) -> None:
        try:
            ensure_captions_window()
            record(
                output,
                poll_interval=0.25,
                timeout=10.0,
                stop_event=self.stop_event,
                on_lines=lambda lines: self.events.put(("lines", lines)),
            )
            self.events.put(("stopped", None))
        except (OSError, RuntimeError, ValueError) as error:
            self.events.put(("error", str(error)))

    def _stop_recording(self) -> None:
        self.stop_event.set()
        try:
            press_live_captions_hotkey()
        except OSError as error:
            self.events.put(("error", str(error)))
        self.is_recording = False
        self.toggle_button.configure(text="Start Live Captions")
        self.browse_button.configure(state="normal")
        self.clear_button.configure(state="normal")
        self.status.set("Saved. Ready")
        self.file_state.set("Not recording")

    def _process_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "lines":
                    self._append_lines(cast(list[str], payload))
                    self.status.set("Recording and saving...")
                    self.total_lines += len(cast(list[str], payload))
                    self.line_count.set(f"{self.total_lines} lines")
                elif event == "error":
                    if self.is_recording:
                        self._stop_recording()
                    self.status.set("Error")
                    messagebox.showerror("Live Captions error", str(payload))
        except queue.Empty:
            pass
        self.root.after(100, self._process_events)

    def _clear_transcript(self) -> None:
        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", "end")
        self.transcript.configure(state="disabled")
        self.total_lines = 0
        self.line_count.set("0 lines")

    def _append_lines(self, lines: list[str]) -> None:
        self.transcript.configure(state="normal")
        for line in lines:
            self.transcript.insert("end", f"{line}\n")
        self.transcript.see("end")
        self.transcript.configure(state="disabled")

    def _update_elapsed(self) -> None:
        if self.is_recording:
            seconds = int(time.monotonic() - self.started_at)
            hours, remainder = divmod(seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            self.elapsed.set(f"{hours:02}:{minutes:02}:{seconds:02}")
        else:
            self.elapsed.set("00:00:00")
        self.root.after(1000, self._update_elapsed)

    def _close(self) -> None:
        if self.is_recording:
            self._stop_recording()
            self.root.after(150, self._close)
            return
        self.root.destroy()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Save Windows Live Captions to a UTF-8 text file."
    )
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        default=Path("live_captions.txt"),
        help="Output text file (default: live_captions.txt)",
    )
    parser.add_argument(
        "--no-toggle",
        action="store_true",
        help="Do not press Win+Ctrl+L; use this when captions are already on.",
    )
    parser.add_argument(
        "--leave-on",
        action="store_true",
        help="Do not press Win+Ctrl+L when stopping with Ctrl+C.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.25,
        help="Seconds between UI reads (default: 0.25).",
    )
    parser.add_argument(
        "--startup-timeout",
        type=float,
        default=10.0,
        help="Seconds to wait for the captions window (default: 10).",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Use the original command-line recorder instead of the desktop app.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.cli:
        if sys.platform != "win32":
            print("The desktop app only runs on Windows.", file=sys.stderr)
            return 2
        root = tk.Tk()
        LiveCaptionsApp(root)
        root.mainloop()
        return 0

    if args.poll_interval <= 0 or args.startup_timeout <= 0:
        print("poll and timeout values must be greater than zero.", file=sys.stderr)
        return 2
    if sys.platform != "win32":
        print("This tool only runs on Windows.", file=sys.stderr)
        return 2

    toggled = not args.no_toggle
    try:
        if toggled:
            press_live_captions_hotkey()
        print(f"Writing captions to {args.output.resolve()}")
        print("Press Ctrl+C to stop.")
        record(
            args.output,
            args.poll_interval,
            args.startup_timeout,
        )
    except KeyboardInterrupt:
        print("\nStopped.")
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    finally:
        if toggled and not args.leave_on:
            press_live_captions_hotkey()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
