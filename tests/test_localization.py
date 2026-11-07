from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest

from scheduler.ui import error_details


ROOT = Path(__file__).resolve().parents[1]


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []

    def handle_starttag(self, tag, attrs):
        self.elements.append({"tag": tag, "attrs": dict(attrs)})


class LocalizationTests(unittest.TestCase):
    def setUp(self):
        self.locales = json.loads((ROOT / "locales.json").read_text())
        self.html = (ROOT / "ui.html").read_text()

    def test_catalogs_cover_all_labels_and_match_placeholders(self):
        self.assertEqual(set(self.locales), {"zh", "en", "fr"})
        keys = set(self.locales["en"])
        for language, strings in self.locales.items():
            self.assertEqual(set(strings), keys, language)
            for key, value in strings.items():
                self.assertTrue(value.strip(), (language, key))
                self.assertEqual(re.findall(r"\{\w+\}", value),
                                 re.findall(r"\{\w+\}", self.locales["en"][key]), (language, key))
        referenced = re.findall(r'data-i18n(?:-placeholder|-aria)?="([^"]+)"', self.html)
        self.assertTrue(set(referenced) <= keys)
        for key in ("credentials_invalid", "profile_required", "cwd_required", "session_invalid", "api_http"):
            self.assertIn(key, keys)

    def test_errors_have_language_independent_codes(self):
        self.assertEqual(error_details("API HTTP 429"), {"error_code": "api_http", "error_params": {"code": "429"}})
        self.assertEqual(error_details("cannot parse credential file")["error_code"], "credentials_invalid")
        self.assertEqual(error_details("unrecognized diagnostic")["error_code"], "operation_error")

    def test_readmes_have_reciprocal_language_links_and_same_commands(self):
        commands = ["start --config", "status --config", "models --config", "run --config", "ui --port", "sbatch examples/slurm.sh"]
        for name in ("README.md", "README.zh-CN.md", "README.fr.md"):
            text = (ROOT / name).read_text()
            for target in ("README.md", "README.zh-CN.md", "README.fr.md"):
                self.assertIn(f"]({target})", text[:200])
            for command in commands:
                self.assertIn(command, text, (name, command))
            self.assertEqual(text.count("``` "), 0)
            self.assertEqual(text.count("```") % 2, 0)

    @unittest.skipUnless(shutil.which("node"), "Node is optional for UI event tests")
    def test_language_switch_preserves_user_data_and_translates_dynamic_messages(self):
        elements = Elements()
        elements.feed(self.html)
        source = self.html.split("<script>", 1)[1].split("</script>", 1)[0]
        source = source.replace("__TRANSLATIONS__", json.dumps(self.locales)).replace("__SESSION_TOKEN__", "synthetic-token")
        payload = json.dumps({"elements": elements.elements, "source": source})
        result = subprocess.run([shutil.which("node"), str(ROOT / "tests/ui_language.cjs")],
                                input=payload, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
