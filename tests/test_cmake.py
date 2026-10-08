from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


TOOL_ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("cmake") and shutil.which("ninja"), "CMake and Ninja required")
class CMakeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="format cmake ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.build = self.root / "build"
        self.root.joinpath("CMakeLists.txt").write_text(
            'cmake_minimum_required(VERSION 3.21)\n'
            'project(FormatFixture LANGUAGES NONE)\n'
            'add_subdirectory(first)\nadd_subdirectory(second)\n'
            'add_custom_target(format-check)\n'
            'add_dependencies(format-check First-format-check Second-format-check)\n'
            'add_custom_target(format)\n'
            'add_dependencies(format First-format Second-format)\n', encoding="utf-8",
        )
        for directory, name in (("first", "First"), ("second", "Second")):
            component = self.root / directory
            component.mkdir()
            subprocess.run(["git", "init", "-q", str(component)], check=True)
            component.joinpath("src").mkdir()
            component.joinpath("src/source.cpp").write_text("int value(){return 1;}\n", encoding="utf-8")
            component.joinpath("CMakeLists.txt").write_text(
                f'include("{TOOL_ROOT.as_posix()}/cmake/FormatValidation.cmake")\n'
                f'format_validation_add_component({name} "${{CMAKE_CURRENT_SOURCE_DIR}}")\n', encoding="utf-8",
            )

    def configure(self):
        return subprocess.run(
            ["cmake", "-S", str(self.root), "-B", str(self.build), "-G", "Ninja",
             f"-DPython3_EXECUTABLE={sys.executable}"],
            capture_output=True, text=True, timeout=60,
        )

    def target(self, name):
        return subprocess.run(["cmake", "--build", str(self.build), "--target", name],
                              capture_output=True, text=True, timeout=60)

    def test_multiple_consumers_and_paths_with_spaces(self):
        configured = self.configure()
        self.assertEqual(0, configured.returncode, configured.stdout + configured.stderr)
        # The default build does not run format checks or rewrite sources.
        original = self.root.joinpath("first/src/source.cpp").read_bytes()
        self.assertEqual(0, self.target("all").returncode)
        self.assertEqual(original, self.root.joinpath("first/src/source.cpp").read_bytes())
        self.assertNotEqual(0, self.target("format-check").returncode)
        fixed = self.target("format")
        self.assertEqual(0, fixed.returncode, fixed.stdout + fixed.stderr)
        checked = self.target("format-check")
        self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)


if __name__ == "__main__":
    unittest.main()
