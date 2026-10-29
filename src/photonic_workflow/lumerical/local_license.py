"""Explicit, temporary localhost licensing using an existing installed license.

No license contents, registry, service configuration or parent environment are
changed. Only processes created by this context are stopped on exit.
"""

from __future__ import annotations

import socket
import subprocess
import time
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

from ..exceptions import InvalidInputError, UnavailableCapabilityError


def _listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _capture(process: Any, owned: dict, psutil: Any) -> None:
    with suppress(psutil.NoSuchProcess, psutil.AccessDenied):
        parent = psutil.Process(process.pid)
        for item in [parent, *parent.children(recursive=True)]:
            owned[(item.pid, item.create_time())] = item


@contextmanager
def local_license_session(install_root: Path | str | None, log_dir: Path, *, timeout_s: float = 15):
    """Yield a localhost endpoint; reuse an existing listener or own one manager.

    This intentionally supports only the installed SERVER localhost form.
    It never installs/imports a license or attempts to repair an invalid license.
    """
    from .runtime import _check_output, discover_install

    try:
        import psutil
    except ImportError as exc:
        raise UnavailableCapabilityError("Local license supervision requires psutil") from exc
    install = discover_install(install_root)
    if not install["available"]:
        raise UnavailableCapabilityError("Lumerical installation not found")
    licensing = Path(install["product_root"]).parent.parent / "Shared Files/licensing"
    manager = licensing / "winx64/lmgrd.exe"
    license_file = (licensing / "license_files" / "ansyslmd").with_suffix(".lic")
    if not manager.is_file() or not license_file.is_file():
        raise UnavailableCapabilityError("No existing local license manager and license file at this installation")
    servers = [line.split() for line in license_file.read_text(encoding="utf-8", errors="replace").splitlines()
               if line.split() and line.split()[0].upper() == "SERVER"]
    server = servers[0] if len(servers) == 1 else None
    local_hosts = {"localhost", "127.0.0.1", socket.gethostname().lower()}
    if not server or len(server) != 4 or server[1].lower() not in local_hosts:
        raise InvalidInputError("Local license mode requires SERVER naming this computer with an explicit port")
    try:
        port = int(server[3])
    except ValueError as exc:
        raise InvalidInputError("Invalid local license port") from exc
    if not 1024 <= port <= 65535:
        raise InvalidInputError("Local license port must be in [1024, 65535]")
    folder = _check_output(Path(log_dir))
    folder.mkdir(parents=True)
    info = {
        "endpoint": f"{port}@localhost", "local_only": True, "persistent_configuration_changed": False,
        "manager_started": False, "reused_existing_listener": False, "owned_processes_exited": True,
        "log_directory": str(folder),
    }
    owned: dict = {}
    process = None
    try:
        if _listening(port):
            info["reused_existing_listener"] = True
        else:
            with (folder / "stdout.log").open("wb") as stream:
                process = subprocess.Popen(
                    [str(manager), "-l", str(folder / "manager.log"), "-z", "-localonly", "-c", str(license_file)],
                    cwd=manager.parent, stdout=stream, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            info["manager_started"] = True
            started = time.monotonic()
            while time.monotonic() - started < timeout_s:
                _capture(process, owned, psutil)
                if _listening(port):
                    break
                if process.poll() is not None:
                    break
                time.sleep(0.1)
            if not _listening(port):
                raise UnavailableCapabilityError(f"Local license manager did not become ready; logs: {folder}")
            # The manager listener precedes its vendor daemon by a short interval.
            time.sleep(1)
            _capture(process, owned, psutil)
        yield info
    finally:
        if process is not None:
            _capture(process, owned, psutil)
            for item in reversed(list(owned.values())):
                with suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                    item.terminate()
            _, alive = psutil.wait_procs(list(owned.values()), timeout=3)
            for item in alive:
                with suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                    item.kill()
            _, alive = psutil.wait_procs(alive, timeout=3)
            info["owned_processes_exited"] = not alive
            if alive:
                raise UnavailableCapabilityError("Temporary local license process cleanup failed")
