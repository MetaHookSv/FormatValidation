import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


TOOL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = TOOL_ROOT / "clang-format-validate.py"
spec = importlib.util.spec_from_file_location("format_validation", SCRIPT)
validation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validation)


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="format validation ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)

    def source(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def run_validator(self, *arguments):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root), *arguments],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
            timeout=30,
        )

    def test_diff_does_not_write_and_fix_is_idempotent(self):
        source = self.source("src/path with spaces.cpp", b"int main(){return 0;}\n")
        original = source.read_bytes()
        result = self.run_validator()
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertIn("---", result.stdout)
        self.assertEqual(original, source.read_bytes())
        self.assertEqual(0, self.run_validator("--fix").returncode)
        formatted = source.read_bytes()
        self.assertNotEqual(original, formatted)
        self.assertEqual(0, self.run_validator().returncode)
        self.assertEqual(0, self.run_validator("--fix").returncode)
        self.assertEqual(formatted, source.read_bytes())

    def test_bom_unicode_and_crlf_survive_fix(self):
        source = self.source(
            "src/unicode.cpp",
            b"\xef\xbb\xbf" + "// 中文注释\r\nint value(){return 42;}\r\n".encode("utf-8"),
        )
        result = self.run_validator("--fix")
        self.assertEqual(0, result.returncode, result.stderr)
        formatted = source.read_bytes()
        self.assertTrue(formatted.startswith(b"\xef\xbb\xbf"))
        self.assertIn("中文注释".encode("utf-8"), formatted)
        self.assertIn(b"\r\n", formatted)
        self.assertNotIn(b"\n", formatted.replace(b"\r\n", b""))
        self.assertEqual(0, self.run_validator().returncode)

    def test_mixed_line_endings_do_not_cause_a_false_difference(self):
        source = self.source("src/mixed.cpp", b"int a;\r\nint b;\n")
        self.assertEqual(0, self.run_validator("--fix").returncode)
        source.write_bytes(source.read_bytes().replace(b"\r\n", b"\n", 1))
        self.assertEqual(0, self.run_validator().returncode)

    def test_ignore_gitignored_and_out_of_scope_sources(self):
        self.source("src/valid.cpp", b"int value;\n")
        self.source("src/vendor/ignored.cpp", b"int ignored(){return 1;}\n")
        self.source("src/cache/cached.cpp", b"int cached(){return 1;}\n")
        self.source("build/generated.cpp", b"int generated(){return 1;}\n")
        self.source("thirdparty/vendor.cpp", b"int vendor(){return 1;}\n")
        self.source(".gitignore", b"src/cache/\n")
        self.source(".clang-format-ignore", b"# third-party copy\nsrc/vendor/\n")
        result = self.run_validator()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("1 files", result.stdout)

    def test_tracked_and_untracked_files_are_both_checked(self):
        self.source("src/tracked.cpp", b"int tracked;\n")
        subprocess.run(["git", "-C", str(self.root), "add", "src/tracked.cpp"], check=True)
        self.source("tests/new.cpp", b"int test(){return 1;}\n")
        self.source("include/new.hpp", b"int header(){return 1;}\n")
        result = self.run_validator()
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertIn("tests/new.cpp", result.stdout)
        self.assertIn("include/new.hpp", result.stdout)

    def test_missing_executable_is_an_error(self):
        self.source("src/source.cpp", b"int value;\n")
        result = self.run_validator("--clang-format-executable", str(self.root / "missing"))
        self.assertEqual(2, result.returncode)
        self.assertIn("error:", result.stderr)

    def test_version_mismatch_is_an_error(self):
        result = self.run_validator("--clang-format-executable", sys.executable)
        self.assertEqual(2, result.returncode)
        self.assertIn("23.1.3", result.stderr)

    def test_non_utf8_is_reported_without_writing(self):
        source = self.source("src/invalid.cpp", b"// \xff\nint value;\n")
        original = source.read_bytes()
        result = self.run_validator("--fix")
        self.assertEqual(2, result.returncode)
        self.assertEqual(original, source.read_bytes())

    def test_empty_scope_is_an_error(self):
        self.assertEqual(2, self.run_validator().returncode)

    def test_failure_has_priority_over_a_format_difference(self):
        self.source("src/invalid.cpp", b"// \xff\n")
        self.source("src/diff.cpp", b"int value(){return 1;}\n")
        result = self.run_validator("-j", "2")
        self.assertEqual(2, result.returncode)
        self.assertIn("src/diff.cpp", result.stdout)

    def test_formatter_failure_is_reported_without_writing(self):
        source = self.source("src/source.cpp", b"int value;\n")
        original = source.read_bytes()
        from unittest.mock import patch
        with patch.object(validation.subprocess, "run", return_value=subprocess.CompletedProcess(
            [], 1, stdout=b"", stderr=b"formatter failed",
        )):
            with self.assertRaisesRegex(validation.ValidationError, "formatter failed"):
                validation.format_file(source, self.root, "formatter", True)
        self.assertEqual(original, source.read_bytes())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_sources_outside_repository_are_rejected(self):
        outside = self.source("outside.cpp", b"int value;\n")
        directory = self.root / "src"
        directory.mkdir()
        try:
            os.symlink(outside, directory / "link.cpp")
        except OSError:
            self.skipTest("creating symlinks is not permitted")
        with self.assertRaisesRegex(validation.ValidationError, "symbolic link"):
            validation.list_files(self.root)


if __name__ == "__main__":
    unittest.main()
