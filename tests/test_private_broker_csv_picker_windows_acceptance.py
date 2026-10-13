import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts.private_broker_csv_picker import allowed_selected_local_csv, select_and_probe

class FilePickerWindowsAcceptance(unittest.TestCase):
    def test_local_csv_allowed(self):
        with tempfile.TemporaryDirectory() as d:
            file=Path(d)/"export.csv"
            file.write_text("sample",encoding="utf-8")
            self.assertEqual(allowed_selected_local_csv(file),file)

    def test_traversal_file_extension_and_missing_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                allowed_selected_local_csv(Path(d)/"missing.csv")
            file=Path(d)/"private.txt"
            file.write_text("secret",encoding="utf-8")
            with self.assertRaises(ValueError):
                allowed_selected_local_csv(file)

    def test_file_symlink_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/"secret.csv";target.write_text("secret")
            link=Path(d)/"alias.csv"
            try:
                link.symlink_to(target)
            except (OSError,NotImplementedError):
                self.skipTest("symlinks unavailable")
            with self.assertRaises(ValueError):
                allowed_selected_local_csv(link)

    def test_oversized_file_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"large.csv"
            with p.open("wb") as f:
                f.truncate(8*1024*1024+1)
            with self.assertRaises(ValueError):
                allowed_selected_local_csv(p)

    def test_dialog_cancel_does_not_probe(self):
        from unittest.mock import MagicMock
        root=MagicMock()
        with patch("tkinter.Tk",return_value=root),patch("tkinter.filedialog.askopenfilename",return_value=""),patch("scripts.private_broker_csv_picker.inspect_header") as inspect:
            self.assertEqual(select_and_probe(),0)
            inspect.assert_not_called()
            root.destroy.assert_called_once()

    @unittest.skipUnless(__import__("os").name=="nt","UNC semantics require Windows")
    def test_windows_unc_blocks_before_file_read(self):
        with self.assertRaises(ValueError):
            allowed_selected_local_csv(r"\\server\share\private.csv")

if __name__=="__main__":
    unittest.main()
