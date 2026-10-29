from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from photonic_workflow.exceptions import IncompatibleVersionError, InvalidInputError, SecurityViolationError
from photonic_workflow.mcp.server import McpError, PhotonicMcpServer
from tests.integration.test_recipe_cli import invoke

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "examples" / "recipes"


class McpRecipeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.read = self.root / "read"
        self.write = self.root / "write"
        self.read.mkdir()
        self.write.mkdir()
        self.server = PhotonicMcpServer(ROOT, [self.read], [self.write])

    def call(self, name: str, **arguments: object) -> dict:
        response = self.server.handle({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        })
        result = response["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(json.loads(result["content"][0]["text"]), result["structuredContent"])
        return result["structuredContent"]

    def test_discovery_is_compact_and_inspection_matches_cli(self) -> None:
        listed = self.call("list_recipes")
        self.assertEqual(len(listed["recipes"]), 6)
        self.assertLess(len(json.dumps(listed)), 5000)
        for item in listed["recipes"]:
            self.assertNotIn("parameter_contract", item)
            recipe_id = item["recipe_id"]
            with self.subTest(recipe_id=recipe_id):
                inspected = self.call("inspect_recipe", recipe_id=recipe_id)
                code, output, error = invoke(["recipe", "inspect", recipe_id, "--json"])
                self.assertEqual((code, error), (0, ""))
                self.assertEqual(inspected, json.loads(output)["data"])
                self.assertFalse(inspected["physics_accepted"])
        self.assertEqual(list(self.write.iterdir()), [])

    def test_all_canonical_artifacts_match_cli_bytes_and_hashes(self) -> None:
        for fixture in FIXTURES.glob("*.json"):
            with self.subTest(fixture=fixture.name):
                request = json.loads(fixture.read_text(encoding="utf-8"))
                target = self.write / fixture.name
                receipt = self.call("render_recipe", request_file=str(fixture), output=str(target))
                code, output, error = invoke([
                    "recipe", "render", request["recipe_id"], "--input", str(fixture), "--json",
                ])
                self.assertEqual((code, error), (0, ""))
                expected = json.loads(output)["data"]["content"].encode("utf-8")
                self.assertEqual(target.read_bytes(), expected)
                self.assertEqual(receipt["sha256"], hashlib.sha256(expected).hexdigest())
                self.assertEqual(receipt["byte_count"], len(expected))
                self.assertFalse(receipt["will_execute"])
                self.assertFalse(receipt["physics_accepted"])
                self.assertNotIn("parameters", receipt)
                self.assertNotIn("content", receipt)
                self.assertNotIn("output", receipt)
                self.assertLess(len(json.dumps(receipt)), 5000)

    def test_java_fragment_matches_cli_without_starting_a_process(self) -> None:
        fixture = FIXTURES / "symmetric-euler-bend.json"
        target = self.write / "bend.java"
        code, output, error = invoke([
            "recipe", "render", "geometry.symmetric-euler-bend", "--input", str(fixture),
            "--renderer", "comsol-java-fragment", "--instance-id", "test-bend", "--json",
        ])
        self.assertEqual((code, error), (0, ""))
        with patch("subprocess.Popen", side_effect=AssertionError("must not start a process")):
            receipt = self.call(
                "render_recipe", request_file=str(fixture), output=str(target),
                renderer="comsol-java-fragment", instance_id="test-bend",
            )
        self.assertEqual(target.read_text(encoding="utf-8"), json.loads(output)["data"]["content"])
        self.assertEqual(receipt["media_type"], "text/x-java-source")

    def test_repeated_call_never_overwrites_artifact_or_request(self) -> None:
        request = self.write / "request.json"
        request.write_bytes((FIXTURES / "li-silicon-1980.json").read_bytes())
        self.server = PhotonicMcpServer(ROOT, [self.write], [self.write])
        before = request.read_bytes()
        with self.assertRaises(InvalidInputError):
            self.call("render_recipe", request_file=str(request), output=str(request))
        self.assertEqual(request.read_bytes(), before)
        target = self.write / "result.json"
        arguments = {"request_file": str(request), "output": str(target)}
        self.call("render_recipe", **arguments)
        before = target.read_bytes()
        with self.assertRaises(InvalidInputError):
            self.call("render_recipe", **arguments)
        self.assertEqual(target.read_bytes(), before)
        self.assertFalse(list(self.write.glob("*.tmp")))

    def test_separate_read_write_roots_and_absolute_paths_are_enforced(self) -> None:
        fixture = FIXTURES / "li-silicon-1980.json"
        outside = self.root / "outside.json"
        outside.write_bytes(fixture.read_bytes())
        for arguments in (
            {"request_file": str(outside), "output": str(self.write / "result.json")},
            {"request_file": str(fixture), "output": str(self.read / "result.json")},
            {"request_file": str(fixture), "output": str(self.write / ".." / "result.json")},
        ):
            with self.subTest(arguments=arguments), self.assertRaises(SecurityViolationError):
                self.call("render_recipe", **arguments)
        with self.assertRaises(McpError):
            self.call("render_recipe", request_file=str(fixture), output="result.json")
        self.server = PhotonicMcpServer(ROOT, [], [])
        with self.assertRaises(McpError):
            self.call("render_recipe", request_file=str(fixture), output=str(self.write / "result.json"))
        self.assertEqual(list(self.write.iterdir()), [])

    def test_invalid_requests_produce_no_artifact(self) -> None:
        valid = (FIXTURES / "li-silicon-1980.json").read_text(encoding="utf-8")
        payload = json.loads(valid)
        invalid = [
            valid.replace('"schema_version":', '"schema_version": "1.0", "schema_version":', 1),
            valid.replace('"recipe_version": "1.0.0"', '"recipe_version": "99.0.0"'),
            json.dumps({**payload, "parameters": {"wavelength_um": True}}),
            json.dumps({**payload, "parameters": {"wavelength_um": float("nan")}}),
            json.dumps({**payload, "parameters": {"wavelength_um": 1.55, "code": "untrusted"}}),
            json.dumps({**payload, "parameters": {"wavelength_um": 1000}}),
        ]
        for index, text in enumerate(invalid):
            request = self.read / "request.json"
            request.write_text(text, encoding="utf-8")
            with self.subTest(index=index), self.assertRaises((InvalidInputError, IncompatibleVersionError)):
                self.call("render_recipe", request_file=str(request), output=str(self.write / "new" / "out.json"))
            self.assertEqual(list(self.write.iterdir()), [])

    def test_unknown_execution_flags_are_rejected(self) -> None:
        with self.assertRaises(McpError):
            self.call(
                "render_recipe", request_file=str(FIXTURES / "li-silicon-1980.json"),
                output=str(self.write / "out.json"), allow_execute=True,
            )
        self.assertEqual(list(self.write.iterdir()), [])

    def test_symlink_output_is_rejected_even_within_write_root(self) -> None:
        link = self.write / "link"
        real = self.write / "real"
        real.mkdir()
        try:
            link.symlink_to(real, target_is_directory=True)
        except OSError:
            self.skipTest("symlink creation unavailable")
        with self.assertRaises(SecurityViolationError):
            self.call(
                "render_recipe", request_file=str(FIXTURES / "li-silicon-1980.json"),
                output=str(link / "out.json"),
            )
        self.assertEqual(list(real.iterdir()), [])

    def test_tool_annotations_distinguish_readers_from_writers(self) -> None:
        tools = {item["name"]: item for item in self.server.tool_list()}
        writers = {"create_project_scaffold", "parse_sweep_table", "compose_circuit", "render_recipe",
                   "export_lumerical_result"}
        self.assertEqual(len(tools), 18)
        for name, tool in tools.items():
            self.assertEqual(tool["annotations"]["readOnlyHint"], name not in writers)
            self.assertFalse(tool["annotations"]["openWorldHint"])
        self.assertFalse(tools["render_recipe"]["annotations"]["destructiveHint"])

    @unittest.skipUnless(os.name == "nt", "Windows junction fixture")
    def test_windows_junction_output_is_rejected(self) -> None:
        link = self.write / "junction"
        real = self.write / "actual"
        real.mkdir()
        created = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                "$ErrorActionPreference = 'Stop'; New-Item -ItemType Junction "
                "-Path $env:PHOTONIC_TEST_LINK -Target $env:PHOTONIC_TEST_TARGET | Out-Null",
            ],
            env={**os.environ, "PHOTONIC_TEST_LINK": str(link), "PHOTONIC_TEST_TARGET": str(real)},
            capture_output=True, text=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        self.assertTrue(link.samefile(real))
        with self.assertRaises(SecurityViolationError):
            self.call(
                "render_recipe", request_file=str(FIXTURES / "li-silicon-1980.json"),
                output=str(link / "out.json"),
            )
        self.assertEqual(list(real.iterdir()), [])

    @unittest.skipUnless(os.name == "nt", "Windows short-path fixture")
    def test_windows_short_path_output_matches_allowed_root(self) -> None:
        import ctypes
        from ctypes import wintypes

        get_short_path = ctypes.WinDLL("kernel32", use_last_error=True).GetShortPathNameW
        get_short_path.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        get_short_path.restype = wintypes.DWORD
        buffer = ctypes.create_unicode_buffer(32768)
        length = get_short_path(str(self.write.resolve()), buffer, len(buffer))
        self.assertGreater(length, 0, ctypes.get_last_error())
        self.assertLess(length, len(buffer))
        short_root = Path(buffer.value)
        if short_root == self.write.resolve():
            self.skipTest("short names are not enabled for the temporary directory")
        receipt = self.call(
            "render_recipe", request_file=str(FIXTURES / "li-silicon-1980.json"),
            output=str(short_root / "short-path.json"),
        )
        target = self.write / "short-path.json"
        self.assertEqual(receipt["sha256"], hashlib.sha256(target.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
