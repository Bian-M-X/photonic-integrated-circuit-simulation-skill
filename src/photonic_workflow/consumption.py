"""Observed Python transformation I/O, separate from planned consumer declarations.

This is provenance instrumentation for trusted local code, not an executable JSON
interface or proof that every input influenced the result. Single trusted writer
per project is required, as for the package's other artifact writers.
"""

from __future__ import annotations

import hashlib
import stat
from collections.abc import Callable, Mapping
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .exceptions import InvalidInputError
from .security import ensure_within_allowed_roots


def resolve_evidence_path(root: Path, relative: str) -> Path:
    """Use exactly the declared root; never search parent/arm/stage fallbacks."""
    if not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative:
        raise InvalidInputError("evidence paths must be nonempty relative POSIX paths")
    path = PurePosixPath(relative)
    if (path.is_absolute() or PureWindowsPath(relative).drive
            or any(part in {"", ".", ".."} for part in relative.split("/"))):
        raise InvalidInputError("evidence paths cannot be absolute, empty or traverse parents")
    base = root.resolve(strict=True)
    checked = ensure_within_allowed_roots(base / relative, [base])
    # Reject indirection even when a link resolves to another in-root file.
    cursor = base
    for part in path.parts:
        cursor = cursor / part
        try:
            metadata = cursor.lstat()
        except FileNotFoundError:
            continue  # Ordinary future paths are valid for planned consumers and outputs.
        attributes = getattr(metadata, "st_file_attributes", 0)
        if stat.S_ISLNK(metadata.st_mode) or attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise InvalidInputError("evidence path cannot traverse a symlink or junction")
    return checked


def _fingerprint(relative: str, content: bytes) -> dict[str, Any]:
    return {"path": relative, "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}


def capture_transformation(
    *, root: Path, consumer: str, inputs: Mapping[str, str], output: str,
    transform: Callable[[Mapping[str, bytes]], bytes], planned_consumers: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Pass the exact hashed input bytes to reviewed code and exclusively create its output.

    Persist the returned receipt separately with a no-overwrite writer. If the
    callback raises, no successful receipt is produced. This does not observe
    native solvers or arbitrary files opened independently by the callback.
    """
    if not inputs or any(not isinstance(k, str) or not k for k in inputs):
        raise InvalidInputError("transformation requires named inputs")
    consumer_path = resolve_evidence_path(root, consumer)
    consumer_bytes = consumer_path.read_bytes()
    destination = resolve_evidence_path(root, output)
    if destination.exists():
        raise InvalidInputError("transformation output already exists")
    records = []
    contents = {}
    for name, relative in inputs.items():
        content = resolve_evidence_path(root, relative).read_bytes()
        contents[name] = content
        records.append({"name": name, **_fingerprint(relative, content)})
    for relative in planned_consumers:
        resolve_evidence_path(root, relative)  # May be absent: it is only a plan.
    result = transform(contents)
    if not isinstance(result, bytes):
        raise InvalidInputError("transformation must return bytes")
    if consumer_path.read_bytes() != consumer_bytes:
        raise InvalidInputError("consumer source changed during transformation")
    destination = resolve_evidence_path(root, output)
    with destination.open("xb") as handle:
        handle.write(result)
    return {"schema_version": "1.0", "path_base": "explicit_root",
            "observation": "instrumented_python_io", "planned_consumers": list(planned_consumers),
            "consumer": _fingerprint(consumer, consumer_bytes), "inputs": records,
            "output": _fingerprint(output, result),
            "limitation": "Observed callback I/O; consumer-source association is caller-declared; "
                          "semantic dependence and native execution not proved."}


def verify_consumption(root: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    """Check current integrity; preserve planned/stale paths and never mint execution evidence."""
    fields = {"schema_version", "path_base", "observation", "planned_consumers", "consumer", "inputs",
              "output", "limitation"}
    if not isinstance(receipt, dict) or set(receipt) != fields:
        raise InvalidInputError("invalid consumption receipt fields")
    if (receipt["schema_version"] != "1.0" or receipt["path_base"] != "explicit_root"
            or receipt["observation"] != "instrumented_python_io"):
        raise InvalidInputError("unsupported consumption receipt version, base or observation")
    if not isinstance(receipt["inputs"], list) or not receipt["inputs"]:
        raise InvalidInputError("receipt must retain observed inputs")
    if not isinstance(receipt["planned_consumers"], list):
        raise InvalidInputError("planned_consumers must be an array")
    issues = []
    names: set[str] = set()
    for role, record in [("consumer", receipt["consumer"]), ("output", receipt["output"]),
                         *(("input", r) for r in receipt["inputs"])]:
        expected = {"path", "sha256", "bytes"} | ({"name"} if role == "input" else set())
        if not isinstance(record, dict) or set(record) != expected:
            raise InvalidInputError("invalid observed artifact record")
        if role == "input":
            name = record["name"]
            if not isinstance(name, str) or not name or name in names:
                raise InvalidInputError("input names must be nonempty and unique")
            names.add(name)
        digest = record["sha256"]
        if (not isinstance(digest, str) or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
                or type(record["bytes"]) is not int or record["bytes"] < 0):
            raise InvalidInputError("invalid artifact fingerprint")
        path = resolve_evidence_path(root, record["path"])
        if not path.is_file():
            issues.append({"role": role, "path": record["path"], "reason": "missing_under_explicit_root"})
        elif _fingerprint(record["path"], path.read_bytes()) != {k: record[k] for k in ("path", "sha256", "bytes")}:
            issues.append({"role": role, "path": record["path"], "reason": "content_changed"})
    stale = [p for p in receipt["planned_consumers"] if not resolve_evidence_path(root, p).is_file()]
    return {"schema_version": "1.0", "integrity": "pass" if not issues else "fail", "issues": issues,
            "stale_planned_consumers": stale, "execution_verified": False,
            "limitation": "Hash integrity is not independent proof of execution or semantic use."}
