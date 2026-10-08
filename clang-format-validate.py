#!/usr/bin/env python3
"""Check or format repository-owned C/C++ sources using a pinned clang-format.

Inspired by DiligentCore/BuildTools/FormatValidation/clang-format-validate.py
and Guillaume Papin's MIT-licensed clang-format wrapper. See LICENSE.
"""

from concurrent.futures import ThreadPoolExecutor
import argparse
import difflib
import fnmatch
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


TOOL_ROOT = Path(__file__).resolve().parent
EXPECTED_VERSION = (TOOL_ROOT / "CLANG_FORMAT_VERSION").read_text(encoding="ascii").strip()
EXTENSIONS = {".c", ".h", ".cpp", ".hpp", ".cc", ".hh", ".cxx", ".hxx", ".c++", ".h++", ".inl", ".ipp"}
SOURCE_DIRECTORIES = ("src", "include", "tests")
BOM = b"\xef\xbb\xbf"


class ValidationError(Exception):
    pass


def find_formatter(explicit):
    executable = explicit or os.environ.get("FORMAT_VALIDATION_CLANG_FORMAT_EXECUTABLE")
    if not executable:
        # Prefer the package installed for this interpreter over a different LLVM
        # version on PATH (including llvm-msvc installations on Windows).
        spec = importlib.util.find_spec("clang_format")
        if spec and spec.origin:
            name = "clang-format.exe" if os.name == "nt" else "clang-format"
            packaged = Path(spec.origin).parent / "data" / "bin" / name
            if packaged.is_file():
                executable = str(packaged)
    executable = executable or shutil.which("clang-format")
    if not executable:
        raise ValidationError(f"clang-format is missing; install with: {sys.executable} -m pip install clang-format=={EXPECTED_VERSION}")
    try:
        result = subprocess.run([executable, "--version"], capture_output=True, check=False)
    except OSError as error:
        raise ValidationError(f"cannot launch clang-format: {error}") from error
    version_output = result.stdout.decode("utf-8", errors="replace").strip()
    match = re.search(r"\bclang-format version\s+(\d+\.\d+\.\d+)(?:\s|$)", version_output)
    if result.returncode or not match or match.group(1) != EXPECTED_VERSION:
        raise ValidationError(f"expected clang-format {EXPECTED_VERSION}, got {version_output or result.stderr.decode('utf-8', errors='replace').strip() or executable}")
    return executable


def ignore_patterns(root):
    path = root / ".clang-format-ignore"
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def is_excluded(relative, patterns):
    for pattern in patterns:
        pattern = pattern.replace("\\", "/").removeprefix("./").lstrip("/")
        if pattern.endswith("/"):
            if relative.startswith(pattern):
                return True
        elif fnmatch.fnmatchcase(relative, pattern):
            return True
    return False


def list_files(root):
    try:
        repository = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                                    capture_output=True, check=True)
        if Path(os.fsdecode(repository.stdout.strip())).resolve() != root.resolve():
            raise ValidationError(f"not an initialized component repository: {root}")
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", *SOURCE_DIRECTORIES],
            capture_output=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValidationError(f"cannot list Git source files in {root}: {error}") from error
    patterns = ignore_patterns(root)
    files = []
    for name in sorted(set(result.stdout.split(b"\0")[:-1])):
        relative = os.fsdecode(name)
        path = root / relative
        if path.suffix.lower() not in EXTENSIONS or is_excluded(relative, patterns):
            continue
        if path.is_symlink():
            raise ValidationError(f"source is a symbolic link: {relative}")
        try:
            path.resolve().relative_to(root.resolve())
        except ValueError as error:
            raise ValidationError(f"source is outside repository: {relative}") from error
        if not path.is_file():
            raise ValidationError(f"source file is missing: {relative}")
        files.append(path)
    if not files:
        raise ValidationError(f"no C/C++ sources found in {root}")
    return files


def normalized_text(data):
    return data.decode("utf-8-sig").replace("\r\n", "\n")


def replace_source(path, original, formatted):
    descriptor, name = tempfile.mkstemp(prefix=".format-validation-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(formatted)
        os.chmod(temporary, path.stat().st_mode)
        if path.read_bytes() != original:
            raise ValidationError(f"source changed during formatting: {path}")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def format_file(path, root, executable, fix):
    try:
        original = path.read_bytes()
        original_text = normalized_text(original)
        result = subprocess.run(
            [executable, f"--style=file:{TOOL_ROOT / '.clang-format'}", "--fallback-style=none", str(path)],
            capture_output=True, check=False,
        )
        if result.returncode:
            raise ValidationError(f"{path}: {result.stderr.decode('utf-8', errors='replace').strip() or 'clang-format failed'}")
        formatted = result.stdout
        if original.startswith(BOM) and not formatted.startswith(BOM):
            formatted = BOM + formatted
        elif not original.startswith(BOM) and formatted.startswith(BOM):
            formatted = formatted[len(BOM):]
        formatted_text = normalized_text(formatted)
        if original_text == formatted_text:
            return "", False
        relative = path.relative_to(root).as_posix()
        if fix:
            # Keep the original predominant newline convention when writing.
            crlf_count = original.count(b"\r\n")
            if crlf_count > original.count(b"\n") - crlf_count:
                formatted = formatted.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            else:
                formatted = formatted.replace(b"\r\n", b"\n")
            replace_source(path, original, formatted)
            return f"formatted {relative}\n", True
        diff = "".join(difflib.unified_diff(original_text.splitlines(keepends=True),
                                           formatted_text.splitlines(keepends=True),
                                           fromfile=f"{relative} (original)", tofile=f"{relative} (formatted)"))
        return diff, True
    except (OSError, UnicodeError) as error:
        raise ValidationError(f"{path}: {error}") from error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="component Git repository root")
    parser.add_argument("--clang-format-executable", help="override the formatter executable")
    parser.add_argument("--fix", action="store_true", help="write formatted sources instead of checking")
    parser.add_argument("-j", "--jobs", type=int, default=min(os.cpu_count() or 1, 8), help="parallel formatter processes")
    args = parser.parse_args(argv)
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    try:
        executable = find_formatter(args.clang_format_executable)
        root = args.root.resolve()
        files = list_files(root)
    except (ValidationError, OSError, UnicodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    changed = 0
    failed = False

    def process(path):
        try:
            return format_file(path, root, executable, args.fix), None
        except ValidationError as error:
            return None, str(error)

    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        for result, error in executor.map(process, files):
            if error:
                print(f"error: {error}", file=sys.stderr)
                failed = True
            else:
                output, differs = result
                sys.stdout.write(output)
                changed += differs
    print(f"clang-format {'fix' if args.fix else 'check'}: {len(files)} files, {changed} {'formatted' if args.fix else 'with differences'}")
    return 2 if failed else (1 if changed and not args.fix else 0)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.exit(main())
