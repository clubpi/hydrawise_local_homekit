from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1] / "custom_components" / "hydrawise_local_homekit"


class SecurityAndMetadataTests(unittest.TestCase):
    def test_pairing_pin_is_not_logged_or_pre_filled(self) -> None:
        bridge = (ROOT / "bridge.py").read_text(encoding="utf-8")
        config_flow = (ROOT / "config_flow.py").read_text(encoding="utf-8")

        self.assertNotIn("PIN %s", bridge)
        self.assertNotIn('default="731-26-420"', config_flow)

    def test_translations_are_valid_utf8_without_mojibake(self) -> None:
        for relative_path in ("strings.json", "translations/de.json"):
            text = (ROOT / relative_path).read_text(encoding="utf-8")
            json.loads(text)
            self.assertNotIn("Ã", text)

    def test_manifest_version_matches_release(self) -> None:
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], "0.3.0")


if __name__ == "__main__":
    unittest.main()
