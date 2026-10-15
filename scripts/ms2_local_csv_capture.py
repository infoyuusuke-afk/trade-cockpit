"""Explicit GUI opt-in: preserve one existing MS2 tick CSV locally, never upload or trade."""
from __future__ import annotations
from pathlib import Path
import re
import sys
from scripts.ms2_offline_acceptance import ROOT, run_acceptance, save_evidence
from scripts.ms2_offline_csv_snapshot import preserve_csv

TICK_NAME = re.compile(r'kioxia_ticks_\d{8}\.csv')


def select_file():
    """Only called interactively. Never automatically searches for market files."""
    import tkinter as tk
    from tkinter import filedialog, messagebox
    root = tk.Tk()
    root.withdraw()
    try:
        consent = messagebox.askokcancel(
            'MS2 offline CSV preservation',
            'STOP the CSV Writer / Watcher before proceeding.\n'
            'Select one existing kioxia_ticks_YYYYMMDD.csv.\n'
            'The source is not changed; a private LOCAL copy is made.\n'
            'No data is uploaded and no order is sent.\n\nContinue?',
            parent=root)
        if not consent:
            return None
        return filedialog.askopenfilename(
            title='Select existing MS2 tick CSV',
            filetypes=[('MS2 tick CSV', 'kioxia_ticks_*.csv')],
            parent=root)
    finally:
        root.destroy()


def capture_selection(selection, repo_root=ROOT):
    """Only fixed states are returned; no selected path or CSV content escapes."""
    if not selection:
        return 'CANCELLED'
    if not isinstance(selection, str):
        return 'BLOCKED'
    chosen = Path(selection)
    if not chosen.is_absolute() or not TICK_NAME.fullmatch(chosen.name):
        return 'BLOCKED'
    try:
        report = run_acceptance()
        if report.get('state') != 'PASS' or report.get('scope') != 'SYNTHETIC_ONLY':
            return 'BLOCKED'
        save_evidence(report)
        result = preserve_csv(repo_root, chosen.parent, chosen.name)
        if (result.get('state') == 'PRESERVED_UNAUTHENTICATED'
                and result.get('source_authenticated') is False
                and result.get('promotion_eligible') is False
                and result.get('real_submit_allowed') is False):
            return 'PRESERVED_UNAUTHENTICATED'
    except Exception:
        pass  # Never echo private paths or exception text.
    return 'BLOCKED'


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if argv:
        print('BLOCKED: ARGUMENTS_NOT_SUPPORTED')
        return 2
    try:
        state = capture_selection(select_file())
    except Exception:
        state = 'BLOCKED'
    if state == 'PRESERVED_UNAUTHENTICATED':
        print('PRESERVED_UNAUTHENTICATED: LOCAL_ONLY')
        return 0
    if state == 'CANCELLED':
        print('CANCELLED: NO_FILE_SELECTED')
        return 3
    print('BLOCKED: LOCAL_CAPTURE_REFUSED')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
