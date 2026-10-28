"""Run in a new empty directory: python trace_transform.py <directory>.

Synthetic power conversion demonstrates observed byte provenance, not COMSOL use.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from photonic_workflow.consumption import capture_transformation, verify_consumption
from photonic_workflow.models.io import atomic_create_text


def main(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    atomic_create_text(directory / "consumer.py", Path(__file__).read_text(encoding="utf-8"))
    atomic_create_text(directory / "amplitudes.json", "[0.5, 0.8]\n")
    receipt = capture_transformation(
        root=directory, consumer="consumer.py", inputs={"amplitudes": "amplitudes.json"},
        output="powers.json",
        transform=lambda files: json.dumps([x * x for x in json.loads(files["amplitudes"])]).encode(),
        planned_consumers=("future_plot.py",),
    )
    atomic_create_text(directory / "receipt.json", json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(verify_consumption(directory, receipt), indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
