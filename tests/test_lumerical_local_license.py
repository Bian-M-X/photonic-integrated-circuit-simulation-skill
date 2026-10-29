"""Local manager lifecycle and child-only environment, using synthetic sockets."""

import os
import socket
import subprocess
import sys

import pytest

from photonic_workflow.exceptions import InvalidInputError
from photonic_workflow.lumerical.local_license import local_license_session
from photonic_workflow.lumerical.runtime import _supervise, run_request


def configure(tmp_path, monkeypatch, port, host="localhost"):
    product = tmp_path / "install/v261/Lumerical"
    product.mkdir(parents=True)
    licensing = product.parent.parent / "Shared Files/licensing"
    (licensing / "winx64").mkdir(parents=True)
    (licensing / "winx64/lmgrd.exe").write_text("synthetic manager")
    (licensing / "license_files").mkdir()
    (licensing / "license_files" / "ansyslmd").with_suffix(".lic").write_text(
        f"SERVER {host} placeholder {port}\nVENDOR ansyslmd\n",
    )
    monkeypatch.setattr("photonic_workflow.lumerical.runtime.discover_install",
                        lambda path: {"available": True, "product_root": str(product)})


def test_reuses_existing_listener_without_spawning_or_changing_environment(tmp_path, monkeypatch):
    before = dict(os.environ)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(5)
        port = listener.getsockname()[1]
        configure(tmp_path, monkeypatch, port)
        monkeypatch.setattr("photonic_workflow.lumerical.local_license.subprocess.Popen",
                            lambda *args, **kwargs: pytest.fail("must preserve the existing listener"))
        with local_license_session(None, tmp_path / "logs") as state:
            assert state["endpoint"] == f"{port}@localhost"
            assert state["reused_existing_listener"] and not state["manager_started"]
        assert listener.fileno() != -1
    assert dict(os.environ) == before


def test_temporary_manager_terminated_on_client_error_and_unrelated_process_preserved(tmp_path, monkeypatch):
    psutil = pytest.importorskip("psutil")
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    configure(tmp_path, monkeypatch, port)
    real_popen = subprocess.Popen
    launched = []

    def fake_manager(command, **kwargs):
        assert "-localonly" in command and "-z" in command
        code = f"import socket,time;s=socket.socket();s.bind(('127.0.0.1',{port}));s.listen(10);time.sleep(30)"
        process = real_popen([sys.executable, "-c", code], **kwargs)
        launched.append(process)
        return process

    unrelated = real_popen([sys.executable, "-c", "import time;time.sleep(30)"])
    monkeypatch.setattr("photonic_workflow.lumerical.local_license.subprocess.Popen", fake_manager)
    try:
        with (pytest.raises(RuntimeError, match="client error"),
              local_license_session(None, tmp_path / "logs") as state):
            assert state["manager_started"] and not state["reused_existing_listener"]
            assert psutil.pid_exists(launched[0].pid)
            raise RuntimeError("client error")
        assert launched[0].poll() is not None
        assert state["owned_processes_exited"]
        assert unrelated.poll() is None
    finally:
        unrelated.kill()
        unrelated.wait(timeout=5)


def test_remote_license_header_is_rejected_before_manager_or_log_creation(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch, 1055, host="remote.example")
    with pytest.raises(InvalidInputError), local_license_session(None, tmp_path / "absent"):
        pytest.fail("remote server accepted as localhost")
    assert not (tmp_path / "absent").exists()


def test_worker_environment_override_is_confined_to_child(tmp_path):
    before = dict(os.environ)
    env = dict(os.environ, ANSYSLMD_LICENSE_FILE="1055@localhost")
    execution = _supervise([sys.executable, "-c", "import os;print(os.environ['ANSYSLMD_LICENSE_FILE'])"],
                           tmp_path, 10, env=env)
    assert execution["exit_code"] == 0
    assert (tmp_path / "worker.log").read_text().strip() == "1055@localhost"
    assert dict(os.environ) == before


@pytest.mark.parametrize("arguments", [
    {"license_server": "1055@localhost", "local_license": True},
    {"license_server": "1055@localhost;echo injected"}, {"license_server": "0@localhost"},
])
def test_invalid_license_options_rejected_without_output(tmp_path, arguments):
    with pytest.raises(InvalidInputError):
        run_request({"schema_version": "1.0", "operation": "mode-waveguide", "parameters": {}},
                    tmp_path / "absent", **arguments)
    assert not (tmp_path / "absent").exists()
