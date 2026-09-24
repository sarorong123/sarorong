"""Small always-on-top Codex usage meter for Windows."""

import argparse
import glob
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime


SETTINGS_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.dirname(os.path.abspath(__file__))),
    "CodexUsageWidget",
    "settings.json",
)
FULL_WIDGET_SIZE = (420, 250)
COMPACT_WIDGET_SIZE = (330, 140)


def resource_path(relative_path):
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


def load_settings():
    defaults = {
        "opacity": 0.9,
        "dock_bottom": True,
        "x": 0,
        "y": 0,
        "compact_mode": False,
        "layout_version": 4,
    }
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as file:
            saved = json.load(file)
        defaults.update({key: saved[key] for key in defaults if key in saved})
        if "compact_mode" not in saved:
            old_options = ("show_usage_bars", "show_refresh_interval", "show_last_updated")
            defaults["compact_mode"] = all(saved.get(key) is False for key in old_options)
        saved_layout_version = saved.get("layout_version", 1)
        if saved_layout_version < 4 and defaults["compact_mode"] and not defaults["dock_bottom"]:
            if "compact_mode" not in saved:
                old_width, old_height = FULL_WIDGET_SIZE
            elif saved_layout_version >= 3:
                old_width, old_height = (220, 64)
            elif saved_layout_version >= 2:
                old_width, old_height = (290, 160)
            else:
                old_width, old_height = (320, 190)
            defaults["x"] = int(defaults["x"]) + old_width - COMPACT_WIDGET_SIZE[0]
            defaults["y"] = int(defaults["y"]) + old_height - COMPACT_WIDGET_SIZE[1]
        defaults["layout_version"] = 4
    except (OSError, ValueError, TypeError):
        pass
    return defaults


def save_settings(settings):
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as file:
        json.dump(settings, file, ensure_ascii=False, indent=2)


def find_codex():
    executable = shutil.which("codex")
    if executable:
        return executable
    base = os.environ.get("LOCALAPPDATA", "")
    matches = glob.glob(os.path.join(base, "OpenAI", "Codex", "bin", "*", "codex.exe"))
    if matches:
        return max(matches, key=os.path.getmtime)
    raise RuntimeError("Codex 실행 파일을 찾지 못했습니다.")


class CodexClient:
    def __init__(self):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = subprocess.Popen(
            [find_codex(), "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            creationflags=flags,
        )
        self.next_id = 0
        self.request("initialize", {
            "clientInfo": {
                "name": "codex_usage_widget",
                "title": "Codex Usage Widget",
                "version": "1.0.0",
            }
        })
        self.send({"method": "initialized"})

    def send(self, message):
        self.proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def request(self, method, params=None):
        self.next_id += 1
        request_id = self.next_id
        message = {"method": method, "id": request_id}
        if params is not None:
            message["params"] = params
        self.send(message)
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("Codex 연결이 종료되었습니다.")
            reply = json.loads(line)
            if reply.get("id") != request_id:
                continue
            if "error" in reply:
                raise RuntimeError(reply["error"].get("message", "사용량 조회 실패"))
            return reply.get("result", {})

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()


def summarize(result):
    limits = result.get("rateLimitsByLimitId") or {}
    if not limits and result.get("rateLimits"):
        limits = {"codex": result["rateLimits"]}
    windows = {}
    for bucket in limits.values():
        if not isinstance(bucket, dict):
            continue
        for name in ("primary", "secondary"):
            value = bucket.get(name)
            if not isinstance(value, dict) or value.get("usedPercent") is None:
                continue
            minutes = value.get("windowDurationMins")
            if minutes is None:
                continue
            # Prefer the default Codex bucket if two buckets share a duration.
            if minutes not in windows or bucket.get("limitId") == "codex":
                windows[minutes] = value
    return windows


def display_lines(windows):
    lines = []
    for minutes, value in sorted(windows.items()):
        label = "5시간" if minutes == 300 else "주간" if minutes == 10080 else f"{minutes}분"
        remaining = max(0, min(100, 100 - float(value["usedPercent"])))
        reset = value.get("resetsAt")
        reset_text = datetime.fromtimestamp(reset).strftime("%m/%d %H:%M") if reset else ""
        lines.append(f"{label}  {remaining:.0f}% 남음" + (f"   ·   {reset_text} 초기화" if reset_text else ""))
    return lines or ["표시할 사용량 데이터가 없습니다."]


def usage_records(windows):
    records = []
    for minutes, value in sorted(windows.items()):
        label = "5시간" if minutes == 300 else "주간" if minutes == 10080 else f"{minutes}분"
        remaining = max(0, min(100, 100 - float(value["usedPercent"])))
        reset = value.get("resetsAt")
        reset_text = datetime.fromtimestamp(reset).strftime("%m/%d %H:%M") if reset else ""
        records.append({"label": label, "remaining": remaining, "reset": reset_text, "resets_at": reset})
    return records


def read_once():
    client = CodexClient()
    try:
        return display_lines(summarize(client.request("account/rateLimits/read")))
    finally:
        client.close()


def run_widget():
    import tkinter as tk

    settings = load_settings()
    root = tk.Tk()
    root.title("사로롱의 Codex 사용량")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", max(0.1, min(1.0, float(settings["opacity"]))))
    root.resizable(False, False)
    transparent_key = "#ff00ff"
    root.configure(bg=transparent_key)
    try:
        root.wm_attributes("-transparentcolor", transparent_key)
    except tk.TclError:
        pass

    width, height = COMPACT_WIDGET_SIZE if settings["compact_mode"] else FULL_WIDGET_SIZE
    canvas = tk.Canvas(root, width=width, height=height, bg=transparent_key, highlightthickness=0, bd=0)
    canvas.pack()
    mascot_source = tk.PhotoImage(file=resource_path(os.path.join("assets", "codex_mascot.png")))
    mascot_image = mascot_source.zoom(3, 3).subsample(5, 5)

    def work_area():
        if sys.platform == "win32":
            try:
                import ctypes

                class Rect(ctypes.Structure):
                    _fields_ = [(name, ctypes.c_long) for name in ("left", "top", "right", "bottom")]

                rect = Rect()
                if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                    return rect.left, rect.top, rect.right, rect.bottom
            except (AttributeError, OSError):
                pass
        return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()

    left, top, right, bottom = work_area()

    def bottom_right_position():
        x = max(left, right - width - 18)
        y = max(top, bottom - height - 12)
        return x, y

    if settings.get("dock_bottom", True):
        x, y = bottom_right_position()
    else:
        x, y = int(settings["x"]), int(settings["y"])
    root.geometry(f"{width}x{height}{x:+d}{y:+d}")

    def rounded_rect(x1, y1, x2, y2, radius, **options):
        points = [
            x1 + radius, y1, x2 - radius, y1, x2, y1,
            x2, y1 + radius, x2, y2 - radius, x2, y2,
            x2 - radius, y2, x1 + radius, y2, x1, y2,
            x1, y2 - radius, x1, y1 + radius, x1, y1,
        ]
        return canvas.create_polygon(points, smooth=True, splinesteps=12, **options)

    view_state = {"records": [], "updated_at": "", "error": "", "loading": True}

    def draw_bubble():
        canvas.delete("all")
        compact = settings["compact_mode"]
        bubble_fill = "#fffdf8"
        bubble_edge = "#d8c9ec"
        if compact:
            rounded_rect(6, 36, 224, 104, 5, fill="#27292e", outline="", tags="art")
            records = view_state["records"]
            if records:
                if len(records) > 1:
                    canvas.create_line(10, 70, 220, 70, fill="#3c3e43", width=1, tags="art")
                now = datetime.now().date()
                for index, record in enumerate(records[:2]):
                    row_y = 55 + index * 30
                    label = "1주" if record["label"] == "주간" else record["label"]
                    canvas.create_text(13, row_y, text=label, anchor="w", fill="#dedfe2", font=("Malgun Gothic", 10, "bold"), tags="art")
                    canvas.create_text(92, row_y, text=f"{record['remaining']:.0f}%", anchor="w", fill="#bfc1c6", font=("Malgun Gothic", 10), tags="art")
                    reset_timestamp = record.get("resets_at")
                    if reset_timestamp:
                        reset_at = datetime.fromtimestamp(reset_timestamp)
                        if reset_at.date() == now:
                            period = "오전" if reset_at.hour < 12 else "오후"
                            hour = reset_at.hour % 12 or 12
                            reset = f"{period} {hour}:{reset_at.minute:02d}"
                        else:
                            reset = f"{reset_at.month}월 {reset_at.day}일"
                    else:
                        reset = "—"
                    canvas.create_text(136, row_y, text=reset, anchor="w", fill="#aeb0b6", font=("Malgun Gothic", 9), tags="art")
            else:
                if view_state["error"]:
                    status = "사용량 조회 실패"
                elif view_state["loading"]:
                    status = "사용량을 불러오는 중…"
                else:
                    status = "표시할 사용량 데이터가 없습니다."
                canvas.create_text(115, 70, text=status, anchor="center", fill="#dedfe2", font=("Malgun Gothic", 9), tags="art")
        else:
            canvas.create_polygon(302, 151, 339, 179, 333, 146, fill=bubble_fill, outline=bubble_edge, width=2, smooth=True, tags="art")
            rounded_rect(14, 13, 383, 163, 18, fill=bubble_fill, outline=bubble_edge, width=2, tags="art")
            canvas.create_text(31, 36, text="사로롱의 Codex 사용량", anchor="w", fill="#4d3e59", font=("Malgun Gothic", 12, "bold"), tags="art")
            canvas.create_text(364, 36, text="10초마다 갱신", anchor="e", fill="#6cab9e", font=("Malgun Gothic", 8), tags="art")
            records = view_state["records"]
            if records:
                for index, record in enumerate(records[:2]):
                    row_y = 69 + index * 35
                    label = record["label"]
                    remaining = record["remaining"]
                    canvas.create_text(31, row_y, text=label, anchor="w", fill="#65596b", font=("Malgun Gothic", 9, "bold"), tags="art")
                    rounded_rect(91, row_y - 5, 243, row_y + 4, 5, fill="#eee9f1", outline="", tags="art")
                    bar_color = "#75cbbb" if remaining > 20 else "#f0bc70" if remaining > 10 else "#e98c93"
                    fill_right = 92 + 150 * remaining / 100
                    if fill_right - 92 >= 4:
                        rounded_rect(92, row_y - 4, fill_right, row_y + 3, 4, fill=bar_color, outline="", tags="art")
                    canvas.create_text(253, row_y, text=f"{remaining:.0f}% 남음", anchor="w", fill="#4d3e59", font=("Malgun Gothic", 9, "bold"), tags="art")
                    reset = record["reset"] or "초기화 시각 없음"
                    canvas.create_text(91, row_y + 12, text=f"초기화 {reset}", anchor="w", fill="#9a8e9e", font=("Malgun Gothic", 8), tags="art")
                if view_state["updated_at"]:
                    canvas.create_text(31, 145, text=f"{view_state['updated_at']} 갱신", anchor="w", fill="#9a8e9e", font=("Malgun Gothic", 8), tags="art")
            else:
                if view_state["error"]:
                    status = f"조회 실패: {view_state['error']}"
                elif view_state["loading"]:
                    status = "사용량을 불러오는 중…"
                else:
                    status = "표시할 사용량 데이터가 없습니다."
                canvas.create_text(31, 82, text=status, anchor="w", fill="#766982", font=("Malgun Gothic", 10), tags="art")
                if view_state["error"]:
                    canvas.create_text(31, 111, text="Codex 앱에 로그인되어 있는지 확인해 주세요.", anchor="w", fill="#9a8e9e", font=("Malgun Gothic", 8), tags="art")
        canvas.create_image(270 if compact else 356, 70 if compact else 185, image=mascot_image, anchor="center", tags="art")

    draw_bubble()

    events = queue.Queue()
    refresh = threading.Event()
    stop = threading.Event()
    refresh.set()

    def worker():
        client = None
        while not stop.is_set():
            refresh.wait(timeout=10)
            refresh.clear()
            if stop.is_set():
                break
            try:
                if client is None or client.proc.poll() is not None:
                    client = CodexClient()
                records = usage_records(summarize(client.request("account/rateLimits/read")))
                updated = datetime.now().strftime("%H:%M:%S")
                events.put((records, updated, ""))
            except Exception as exc:
                if client:
                    client.close()
                    client = None
                events.put(([], "", str(exc)))
        if client:
            client.close()

    threading.Thread(target=worker, daemon=True).start()

    def update_ui():
        try:
            while True:
                records, updated_at, error = events.get_nowait()
                view_state.update(records=records, updated_at=updated_at, error=error, loading=False)
                draw_bubble()
        except queue.Empty:
            pass
        if not stop.is_set():
            root.after(200, update_ui)

    menu = tk.Menu(root, tearoff=0)
    menu.add_command(label="새로고침", command=refresh.set)
    menu.add_separator()

    compact_choice = tk.BooleanVar(value=settings["compact_mode"])

    def toggle_compact():
        nonlocal width, height
        next_width, next_height = COMPACT_WIDGET_SIZE if compact_choice.get() else FULL_WIDGET_SIZE
        if settings["dock_bottom"]:
            width, height = next_width, next_height
            x, y = bottom_right_position()
        else:
            x = root.winfo_x() + width - next_width
            y = root.winfo_y() + height - next_height
            width, height = next_width, next_height
            settings["x"], settings["y"] = x, y
        settings["compact_mode"] = compact_choice.get()
        canvas.configure(width=width, height=height)
        root.geometry(f"{width}x{height}{x:+d}{y:+d}")
        save_settings(settings)
        draw_bubble()

    menu.add_checkbutton(label="간소화", variable=compact_choice, command=toggle_compact)

    menu.add_separator()
    dock_choice = tk.BooleanVar(value=bool(settings.get("dock_bottom", True)))

    def toggle_dock():
        settings["dock_bottom"] = dock_choice.get()
        if settings["dock_bottom"]:
            x, y = bottom_right_position()
            root.geometry(f"+{x}+{y}")
        else:
            settings["x"] = root.winfo_x()
            settings["y"] = root.winfo_y()
        save_settings(settings)

    menu.add_checkbutton(label="모니터 아래쪽에 붙이기", variable=dock_choice, command=toggle_dock)
    opacity_menu = tk.Menu(menu, tearoff=0)
    menu.add_cascade(label="투명도", menu=opacity_menu)

    def set_opacity(percent):
        settings["opacity"] = percent / 100
        root.attributes("-alpha", settings["opacity"])
        save_settings(settings)

    for percent in range(100, 0, -10):
        opacity_menu.add_command(label=f"{percent}%", command=lambda value=percent: set_opacity(value))
    menu.add_separator()

    def quit_app():
        stop.set()
        refresh.set()
        root.destroy()

    menu.add_command(label="종료", command=quit_app)
    root.protocol("WM_DELETE_WINDOW", quit_app)

    def show_menu(event):
        menu.tk_popup(event.x_root, event.y_root)
        menu.grab_release()

    move_drag = {}

    def start_move(event):
        move_drag["x"] = event.x_root - root.winfo_x()
        move_drag["y"] = event.y_root - root.winfo_y()
        if settings.get("dock_bottom", True):
            settings["dock_bottom"] = False
            dock_choice.set(False)

    def move_window(event):
        if "x" in move_drag:
            next_x = event.x_root - move_drag["x"]
            next_y = event.y_root - move_drag["y"]
            root.geometry(f"{next_x:+d}{next_y:+d}")

    def finish_move(_event):
        if "x" in move_drag:
            settings["x"] = root.winfo_x()
            settings["y"] = root.winfo_y()
            save_settings(settings)
        move_drag.clear()

    canvas.bind("<Button-3>", show_menu)
    canvas.bind("<ButtonPress-1>", start_move)
    canvas.bind("<B1-Motion>", move_window)
    canvas.bind("<ButtonRelease-1>", finish_move)

    update_ui()
    root.mainloop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Read usage once and exit")
    args = parser.parse_args()
    if args.once:
        print("\n".join(read_once()))
    else:
        run_widget()
