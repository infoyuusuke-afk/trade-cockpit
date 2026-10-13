"""Opt-in offline GUI for private broker CSV header reconnaissance.

User explicitly picks a local CSV via Windows file dialog. Never uploads,
writes, imports transactions, authenticates a broker, or changes trading state.
Do not display the source path, unrecognized headers or any trade row.
"""
from pathlib import Path

try:
    from .private_broker_jp_header_probe import inspect_header
    from .private_broker_csv_preflight import MAX_BYTES
except ImportError:
    from private_broker_jp_header_probe import inspect_header
    from private_broker_csv_preflight import MAX_BYTES

SAFE_FIELDS = (
    "status", "format_family_candidate", "encoding_candidate",
    "columns_count", "recognized_column_count", "duplicate_header_count",
)
WARN = "診断結果は候補判定のみ。証券会社の真正性・実約定・実損益の証明ではありません。"

def safe_report(report):
    """Privacy-safe, fixed-key summary only; never echo files or row values."""
    if not isinstance(report, dict):
        return "診断できませんでした。\\n" + WARN
    data = []
    for key in SAFE_FIELDS:
        value = report.get(key)
        if key in ("columns_count", "recognized_column_count", "duplicate_header_count"):
            if type(value) is int and 0 <= value <= 1000:
                data.append(f"{key}: {value}")
        elif key in ("status", "format_family_candidate", "encoding_candidate"):
            # Known enums only. Never echo arbitrary field text or values.
            accepted = {
                "status": ("BLOCKED", "JP_HEADER_CANDIDATE_ONLY"),
                "format_family_candidate": (
                    "TRADE_HISTORY_LEGACY_CANDIDATE",
                    "EXECUTION_INQUIRY_CANDIDATE",
                    "AMBIGUOUS_MIXED_HEADERS",
                    "UNKNOWN_BROKER_CSV_TYPE",
                ),
                "encoding_candidate": ("cp932", "utf-8-sig"),
            }
            if value in accepted[key]:
                data.append(f"{key}: {value}")
    return ("\\n".join(data) if data else "形式不明：BLOCKED") + "\\n" + WARN

def select_and_probe():
    """One user-initiated file selection only, with no persistent output."""
    import tkinter as tk
    from tkinter import filedialog, messagebox
    root=tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        file_path=filedialog.askopenfilename(
            parent=root,
            title="非公開CSVを選択（外部送信なし）",
            filetypes=(("CSV", "*.csv"),),
        )
        if not file_path:
            return 0
        try:
            file=Path(file_path)
            if file.suffix.lower()!=".csv" or file.is_symlink() or not file.is_file():
                raise ValueError("NOT_LOCAL_CSV")
            if file.stat().st_size>MAX_BYTES:
                raise ValueError("FILE_TOO_LARGE")
            report=inspect_header(file)
            messagebox.showinfo("約定CSV形式診断｜非公開",safe_report(report),parent=root)
            return 0 if report.get("status")=="JP_HEADER_CANDIDATE_ONLY" else 2
        except (OSError,ValueError,UnicodeError):
            messagebox.showwarning(
                "約定CSV形式診断｜保留",
                "ファイル形式を検証できません。取込み・照合・EV学習は実行しません。",
                parent=root,
            )
            return 2
    finally:
        root.destroy()

if __name__=="__main__":
    raise SystemExit(select_and_probe())
