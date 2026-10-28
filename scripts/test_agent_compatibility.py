#!/usr/bin/env python3
"""Cross-agent compatibility checks for the public skill payload.

Verifies that the skill at the repository root stays discoverable and
well-formed for Claude Code (~/.claude/skills/<name>/), Codex and the
ChatGPT desktop app (~/.codex/skills/<name>/), and generic agent
frameworks that rely only on a standard YAML parser. Discovery is
simulated against a temporary skills root so the checked-in payload can
never drift into a layout that an installed agent cannot find.
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
from pathlib import Path

import yaml
from test_skill_metadata import MetadataError, validate_skill

ROOT = Path(__file__).resolve().parents[1]
SKILL_MD = ROOT / "SKILL.md"
AGENTS_DIR = ROOT / "agents"
REFERENCES_DIR = ROOT / "references"
ASSETS_DIR = ROOT / "assets"
SAFE_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# Exercise the canonical name and the previous discovery folder during migration.
# The checkout directory itself need not be renamed to install the new skill.
INSTALL_DIR_NAMES = ("photonic-integrated-circuit-simulation", "photonic-waveguide-optics", ROOT.name)
REQUIRED_AGENT_SECTIONS = ("## Purpose", "## Read First", "## Output Contract")
REQUIRED_PAYLOAD_DIRS = ("agents", "references")


def _payload_files() -> list[Path]:
    """Every skill payload file that an agent would read or list."""
    files = [SKILL_MD]
    for directory in (AGENTS_DIR, REFERENCES_DIR):
        if directory.is_dir():
            files.extend(sorted(directory.glob("*.md")))
    if ASSETS_DIR.is_dir():
        files.extend(sorted(p for p in ASSETS_DIR.rglob("*") if p.is_file()))
    return files


def _check_text_payload(files: list[Path]) -> None:
    """Generic agent readers assume UTF-8 text without binary bytes."""
    for path in files:
        raw = path.read_bytes()
        if b"\x00" in raw:
            raise MetadataError(f"{path.relative_to(ROOT)} contains NUL bytes; not a text payload")
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MetadataError(f"{path.relative_to(ROOT)} is not valid UTF-8: {exc}") from exc


def _check_no_nested_skill() -> None:
    """A nested SKILL.md would shadow or break single-level discovery."""
    for directory in (AGENTS_DIR, REFERENCES_DIR):
        for candidate in directory.rglob("SKILL.md"):
            raise MetadataError(f"unexpected nested skill declaration: {candidate.relative_to(ROOT)}")


def _check_claude_agent_docs() -> None:
    """Claude Code agent cards must be uniform, titled, and uniquely named."""
    agent_files = sorted(AGENTS_DIR.glob("*-agent.md"))
    if not agent_files:
        raise MetadataError("agents/ must contain at least one *-agent.md file")
    seen_names: set[str] = set()
    for path in agent_files:
        text = path.read_text(encoding="utf-8")
        first_line = text.splitlines()[0] if text.splitlines() else ""
        stem_name = path.stem.removesuffix("-agent")
        expected_title = " ".join(part.title() for part in stem_name.split("-")) + " Agent"
        # Case-insensitive so preserved acronyms such as "MCP" still pass.
        if first_line.casefold() != f"# {expected_title}".casefold():
            raise MetadataError(f"{path.name} must start with '# {expected_title}'")
        missing = [section for section in REQUIRED_AGENT_SECTIONS if section not in text]
        if missing:
            raise MetadataError(f"{path.name} is missing required sections: {', '.join(missing)}")
        if stem_name in seen_names:
            raise MetadataError(f"duplicate agent name: {stem_name}")
        seen_names.add(stem_name)


def _check_codex_ui_metadata(name: str) -> None:
    """The Codex/ChatGPT desktop app keys off agents/openai.yaml."""
    openai_path = AGENTS_DIR / "openai.yaml"
    if not openai_path.is_file():
        raise MetadataError("agents/openai.yaml is required for Codex/ChatGPT UI metadata")
    if f"${name}" not in openai_path.read_text(encoding="utf-8"):
        raise MetadataError(f"agents/openai.yaml must reference ${name}")


def _simulate_discovery(install_name: str) -> None:
    """Copy the payload into a temp <skills-root>/<name>/ layout and assert the
    discovery contract that both Claude Code and Codex rely on."""
    if not SAFE_NAME.fullmatch(install_name):
        raise MetadataError(f"install directory name {install_name!r} must use lower-case hyphen-case")
    with tempfile.TemporaryDirectory() as tmp:
        skill_root = Path(tmp) / install_name
        skill_root.mkdir()
        for path in (SKILL_MD, AGENTS_DIR, REFERENCES_DIR):
            target = skill_root / path.name
            if path.is_dir():
                shutil.copytree(path, target)
            else:
                shutil.copy2(path, target)
        validate_skill(skill_root / "SKILL.md")  # frontmatter must survive the move
        for required in REQUIRED_PAYLOAD_DIRS:
            if not (skill_root / required).is_dir():
                raise MetadataError(f"discovered skill {install_name!r} is missing {required}/")
        for candidate in skill_root.rglob("SKILL.md"):
            if candidate.parent != skill_root:
                raise MetadataError(f"nested SKILL.md would break discovery: {candidate}")


def main() -> int:
    try:
        name = validate_skill()
        if not SAFE_NAME.fullmatch(name):
            raise MetadataError("SKILL.md name must use lower-case hyphen-case")
        _check_text_payload(_payload_files())
        _check_no_nested_skill()
        _check_claude_agent_docs()
        _check_codex_ui_metadata(name)
        for install_name in INSTALL_DIR_NAMES:
            _simulate_discovery(install_name)
    except (MetadataError, OSError, UnicodeError, yaml.YAMLError) as exc:
        print(f"Agent compatibility validation failed: {exc}", file=sys.stderr)
        return 1
    print("Skill payload verified for Claude Code, Codex, and generic agent discovery.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
