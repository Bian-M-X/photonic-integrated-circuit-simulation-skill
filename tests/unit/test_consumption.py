from __future__ import annotations

import copy
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from photonic_workflow.consumption import capture_transformation, resolve_evidence_path, verify_consumption
from photonic_workflow.exceptions import InvalidInputError


class ConsumptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "consumer.py").write_text("# reviewed test transform", encoding="utf-8")
        (self.root / "input.txt").write_bytes(b"12")

    def capture(self) -> dict:
        return capture_transformation(root=self.root, consumer="consumer.py", inputs={"value": "input.txt"},
                                      output="result.txt", transform=lambda x: str(int(x["value"]) * 2).encode(),
                                      planned_consumers=("old-postprocessor.py",))

    def test_observed_bytes_and_stale_plan_are_separate(self) -> None:
        receipt = self.capture()
        self.assertEqual((self.root / "result.txt").read_bytes(), b"24")
        result = verify_consumption(self.root, receipt)
        self.assertEqual(result["integrity"], "pass")
        self.assertEqual(result["stale_planned_consumers"], ["old-postprocessor.py"])
        self.assertFalse(result["execution_verified"])
        self.assertFalse((self.root / "old-postprocessor.py").exists())

    def test_changed_input_output_and_consumer_each_invalidate_integrity(self) -> None:
        receipt = self.capture()
        for relative in ("input.txt", "result.txt", "consumer.py"):
            with self.subTest(relative=relative):
                path = self.root / relative
                before = path.read_bytes()
                path.write_bytes(b"changed")
                self.assertEqual(verify_consumption(self.root, receipt)["integrity"], "fail")
                path.write_bytes(before)

    def test_wrong_base_is_reported_and_no_fallback(self) -> None:
        receipt = self.capture()
        other = self.root / "stage"
        other.mkdir()
        result = verify_consumption(other, receipt)
        self.assertEqual(result["integrity"], "fail")
        self.assertEqual(len(result["issues"]), 3)

    def test_no_overwrite_and_no_success_on_callback_error(self) -> None:
        self.capture()
        with self.assertRaises(InvalidInputError):
            self.capture()
        with self.assertRaises(ZeroDivisionError):
            capture_transformation(root=self.root, consumer="consumer.py", inputs={"x": "input.txt"},
                                   output="failed.txt", transform=lambda _: 1 / 0)
        self.assertFalse((self.root / "failed.txt").exists())

    def test_absolute_traversal_and_ambiguous_paths_rejected(self) -> None:
        for relative in ("../input.txt", "/input.txt", "C:/input.txt", "a/../input.txt", "./input.txt",
                         "a\\input.txt", "a//input.txt", "input.txt:stream"):
            with self.subTest(relative=relative), self.assertRaises(InvalidInputError):
                resolve_evidence_path(self.root, relative)

    def test_metadata_alone_cannot_be_verified(self) -> None:
        with self.assertRaises(InvalidInputError):
            verify_consumption(self.root, {"planned_consumers": ["consumer.py"]})
        receipt = self.capture()
        changed = copy.deepcopy(receipt)
        changed["inputs"] = []
        with self.assertRaises(InvalidInputError):
            verify_consumption(self.root, changed)

    def test_dangling_reparse_points_rejected_at_each_component(self) -> None:
        # Model Windows junction metadata without requiring Windows or Path.is_junction (3.12+).
        original_lstat = Path.lstat
        for relative, component in (("junction", "junction"), ("junction/file.txt", "junction")):
            with self.subTest(relative=relative):
                junction = self.root.resolve() / component
                self.assertFalse(junction.exists())

                def lstat(path: Path, junction: Path = junction):
                    if path == junction:
                        return SimpleNamespace(st_mode=stat.S_IFDIR,
                                               st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
                    return original_lstat(path)

                with patch.object(Path, "lstat", lstat), self.assertRaises(InvalidInputError):
                    resolve_evidence_path(self.root, relative)

    def test_symlink_mode_rejected_without_windows_attributes(self) -> None:
        original_lstat = Path.lstat
        link = self.root.resolve() / "link"

        def lstat(path: Path):
            if path == link:
                return SimpleNamespace(st_mode=stat.S_IFLNK)
            return original_lstat(path)

        with patch.object(Path, "lstat", lstat), self.assertRaises(InvalidInputError):
            resolve_evidence_path(self.root, "link/file.txt")

    def test_missing_ordinary_future_paths_allowed(self) -> None:
        self.assertEqual(resolve_evidence_path(self.root, "future/nested/output.txt"),
                         self.root.resolve() / "future/nested/output.txt")

    def test_lstat_errors_other_than_missing_fail_closed(self) -> None:
        original_lstat = Path.lstat
        blocked = self.root.resolve() / "blocked"
        for error in (PermissionError("denied"), OSError("unreadable metadata")):
            with self.subTest(error=type(error).__name__):
                def lstat(path: Path, error: OSError = error):
                    if path == blocked:
                        raise error
                    return original_lstat(path)

                with patch.object(Path, "lstat", lstat), self.assertRaises(type(error)):
                    resolve_evidence_path(self.root, "blocked/file.txt")
