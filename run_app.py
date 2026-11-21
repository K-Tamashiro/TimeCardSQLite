"""Standalone launcher for Personal TimeCard for Free Lance."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import threading
import webbrowser
from timecard.application import mark_shutting_down, reset_shutting_down
from timecard.auth import revoke_all_sessions
from timecard.db import close_all, configure, current_db_path
from timecard.server import create_server
from timecard.version import APP_COPYRIGHT, APP_NAME, APP_VERSION

DEFAULT_PORT = 18573


def _bind_server(host, preferred_port, allow_fallback=True):
    try:
        return create_server(host=host, port=preferred_port)
    except OSError:
        if allow_fallback and preferred_port != 0:
            return create_server(host=host, port=0)
        raise


def _open_folder(folder_path):
    p = str(folder_path)
    if os.name == "nt":
        os.startfile(p)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", p])
    else:
        subprocess.Popen(["xdg-open", p])


def _run_gui(server, url, db_path):
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.title(APP_NAME)
    root.resizable(False, False)
    root.configure(bg="#111b22")

    frame = tk.Frame(root, bg="#111b22", padx=22, pady=18)
    frame.pack(fill="both", expand=True)

    tk.Label(
        frame,
        text=APP_NAME,
        font=("Meiryo UI", 13, "bold"),
        fg="#f1f5f9",
        bg="#111b22",
    ).pack(anchor="w")
    tk.Label(
        frame,
        text="v" + APP_VERSION + "  |  " + APP_COPYRIGHT,
        font=("Meiryo UI", 9),
        fg="#94b0c2",
        bg="#111b22",
    ).pack(anchor="w", pady=(2, 12))

    tk.Label(
        frame,
        text="ローカルサーバー稼働中：",
        font=("Meiryo UI", 9),
        fg="#c3d1db",
        bg="#111b22",
    ).pack(anchor="w")
    tk.Label(
        frame,
        text=url,
        font=("Consolas", 10, "bold"),
        fg="#70d8f0",
        bg="#111b22",
    ).pack(anchor="w", pady=(0, 8))

    tk.Label(
        frame,
        text="データ保存先：" + str(db_path),
        font=("Meiryo UI", 8),
        fg="#94b0c2",
        bg="#111b22",
        wraplength=420,
        justify="left",
    ).pack(anchor="w", pady=(0, 8))

    tk.Label(
        frame,
        text="※ 使用中はこの画面を開いたままにしてください（閉じるとログアウトして終了します）",
        font=("Meiryo UI", 8),
        fg="#f5c97a",
        bg="#111b22",
        wraplength=420,
        justify="left",
    ).pack(anchor="w", pady=(0, 14))

    btn_row = tk.Frame(frame, bg="#111b22")
    btn_row.pack(fill="x")

    tk.Button(
        btn_row,
        text="ブラウザで開く",
        font=("Meiryo UI", 10, "bold"),
        bg="#087687",
        fg="#ffffff",
        activebackground="#0b95aa",
        activeforeground="#ffffff",
        relief="flat",
        padx=14,
        pady=7,
        cursor="hand2",
        command=lambda: webbrowser.open(url),
    ).pack(side="left", padx=(0, 8))

    tk.Button(
        btn_row,
        text="データフォルダを開く",
        font=("Meiryo UI", 9),
        bg="#254254",
        fg="#f1f5f9",
        activebackground="#325a72",
        activeforeground="#ffffff",
        relief="flat",
        padx=12,
        pady=7,
        cursor="hand2",
        command=lambda: _open_folder(Path(db_path).parent),
    ).pack(side="left", padx=(0, 8))

    def shutdown():
        try:
            mark_shutting_down()
            try:
                revoke_all_sessions()
            except Exception:
                pass
            server.shutdown()
            server.server_close()
        finally:
            close_all()
            root.destroy()

    def confirm_and_shutdown():
        ok = messagebox.askyesno(
            APP_NAME,
            "アプリを終了しますか？\n\n終了するとシステムからログアウトされ、ローカルサーバーが停止します。\n（開いているブラウザ画面からは操作できなくなります）",
            icon="question",
            parent=root,
        )
        if not ok:
            return
        shutdown()

    tk.Button(
        btn_row,
        text="終了",
        font=("Meiryo UI", 9, "bold"),
        bg="#8c2d3a",
        fg="#ffffff",
        activebackground="#a83847",
        activeforeground="#ffffff",
        relief="flat",
        padx=14,
        pady=7,
        cursor="hand2",
        command=confirm_and_shutdown,
    ).pack(side="right")

    root.protocol("WM_DELETE_WINDOW", confirm_and_shutdown)
    root.after(250, lambda: webbrowser.open(url))
    root.mainloop()


def main(argv=None):
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"Port number (default: {DEFAULT_PORT}, falls back to auto if busy; 0 = auto)",
    )
    parser.add_argument("--data-dir", default="", help="Custom directory for SQLite database")
    parser.add_argument("--headless", action="store_true", help="Run without GUI launcher window")
    parser.add_argument("--no-browser", action="store_true", help="Do not open web browser automatically")
    args = parser.parse_args(argv)

    if args.data_dir:
        configure(Path(args.data_dir) / "timecard.db")
    else:
        configure(None)

    reset_shutting_down()
    revoke_all_sessions()

    db_path = current_db_path()
    if args.port is None:
        server = _bind_server(args.host, DEFAULT_PORT, allow_fallback=True)
    else:
        server = _bind_server(args.host, args.port, allow_fallback=False)
    actual_port = server.server_address[1]
    url = f"http://{args.host}:{actual_port}/"

    if args.headless:
        print(f"{APP_NAME} v{APP_VERSION} running at {url}")
        print(f"Database: {db_path}")
        if not args.no_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            mark_shutting_down()
            try:
                revoke_all_sessions()
            except Exception:
                pass
            server.server_close()
            close_all()
        return

    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        _run_gui(server, url, db_path)
    except Exception:
        # Fallback to headless mode if GUI is unavailable
        if not args.no_browser:
            webbrowser.open(url)
        try:
            t.join()
        except KeyboardInterrupt:
            mark_shutting_down()
            try:
                revoke_all_sessions()
            except Exception:
                pass
            server.shutdown()
            server.server_close()
            close_all()


if __name__ == "__main__":
    main()
