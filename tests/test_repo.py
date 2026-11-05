"""Repository hygiene that would otherwise only show up after a release."""
import json
import py_compile
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.support import REPO


class Repo(unittest.TestCase):

    def test_manifest_is_valid_and_points_at_real_files(self):
        manifest = json.loads((REPO / "manifest.json").read_text())
        for key in ("schemaVersion", "id", "name", "version", "author", "license", "kinds", "entryPoints"):
            self.assertIn(key, manifest)
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")
        for kind, entry in manifest["entryPoints"].items():
            self.assertIn(kind, manifest["kinds"])
            self.assertTrue((REPO / entry).is_file(), entry)

    def test_changelog_has_an_entry_for_the_manifest_version(self):
        version = json.loads((REPO / "manifest.json").read_text())["version"]
        top = re.search(r"^## (\S+)", (REPO / "CHANGELOG.md").read_text(), re.M).group(1)
        self.assertEqual(top, version, "bump CHANGELOG.md and manifest.json together")

    def test_python_compiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            for path in [REPO / "recolor.py", *(REPO / "src").glob("*.py"), *(REPO / "tests").glob("*.py")]:
                py_compile.compile(str(path), cfile=str(Path(tmp, path.name + "c")), doraise=True)

    def test_shell_scripts_parse(self):
        for path in [REPO / "cursor-accent", *(REPO / "tools").glob("*.sh")]:
            result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, f"{path.name}: {result.stderr}")

    def test_scripts_are_executable(self):
        for path in [REPO / "recolor.py", REPO / "cursor-accent", REPO / "src/cursor_utils.py",
                     REPO / "src/build_theme.py", *(REPO / "tools").glob("*.sh")]:
            self.assertTrue(path.stat().st_mode & 0o111, f"{path.name} is not executable")

    def test_vendored_build_tool_is_unmodified(self):
        # NOTICE.md says src/cursor_utils.py is upstream's file as pinned.
        notice = (REPO / "NOTICE.md").read_text()
        self.assertIn("`src/cursor_utils.py` is unmodified", notice)


if __name__ == "__main__":
    unittest.main()
