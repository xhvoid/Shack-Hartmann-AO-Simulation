"""AO-REF-019 smoke-runner contract: kernel isolation, budget, injection.

The static tests always run; the two integration tests spawn a real kernel
and therefore skip in environments without the ``notebook-test`` extra
(``nbclient`` + ``ipykernel``), exactly like the notebook CI lanes.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# scripts/ is a path-addressed tool directory, not an importable package;
# loading the runner by file keeps collection working under both
# `python -m pytest` (repository root on sys.path) and the bare `pytest`
# entry point (repository root absent).
_RUNNER_SPEC = importlib.util.spec_from_file_location(
    "run_notebook_smoke_for_runner_tests",
    ROOT / "scripts" / "run_notebook_smoke.py",
)
assert _RUNNER_SPEC is not None and _RUNNER_SPEC.loader is not None
runner = importlib.util.module_from_spec(_RUNNER_SPEC)
sys.modules[_RUNNER_SPEC.name] = runner
_RUNNER_SPEC.loader.exec_module(runner)


def test_kernel_environment_always_forces_headless_matplotlib(monkeypatch):
    monkeypatch.setenv("MPLBACKEND", "pdf")
    assert runner._kernel_environment()["MPLBACKEND"] == "Agg"
    monkeypatch.delenv("MPLBACKEND")
    assert runner._kernel_environment()["MPLBACKEND"] == "Agg"


def _notebook_with_parameter_tags(nbformat, tag_counts: int):
    notebook = nbformat.v4.new_notebook()
    notebook.cells.append(nbformat.v4.new_markdown_cell("narrative"))
    for _ in range(tag_counts):
        tagged = nbformat.v4.new_code_cell("FAST_SMOKE = False")
        tagged.metadata["tags"] = [runner.PARAMETERS_TAG]
        notebook.cells.append(tagged)
    notebook.cells.append(nbformat.v4.new_code_cell("result = FAST_SMOKE"))
    return notebook


def test_fast_smoke_injection_lands_directly_after_the_parameters_cell():
    nbformat = pytest.importorskip("nbformat")
    notebook = _notebook_with_parameter_tags(nbformat, 1)
    runner._inject_fast_smoke_override(notebook)
    override = notebook.cells[2]
    assert override.cell_type == "code"
    assert override.source == runner.FAST_SMOKE_OVERRIDE_SOURCE
    assert override.metadata["tags"] == ["injected-parameters"]
    assert notebook.cells[1].source == "FAST_SMOKE = False"
    assert notebook.cells[3].source == "result = FAST_SMOKE"


@pytest.mark.parametrize("tag_counts", [0, 2])
def test_fast_smoke_requires_exactly_one_parameters_cell(tag_counts):
    nbformat = pytest.importorskip("nbformat")
    notebook = _notebook_with_parameter_tags(nbformat, tag_counts)
    with pytest.raises(SystemExit, match="exactly one code cell tagged"):
        runner._inject_fast_smoke_override(notebook)


def test_network_guard_is_injected_as_the_first_executed_cell():
    nbformat = pytest.importorskip("nbformat")
    notebook = _notebook_with_parameter_tags(nbformat, 1)
    # Mirror the runner's order: fast-smoke first, then the guard at index 0.
    runner._inject_fast_smoke_override(notebook)
    runner._inject_network_guard(notebook)
    assert notebook.cells[0].source == runner.NETWORK_GUARD_SOURCE
    assert notebook.cells[0].metadata["tags"] == ["injected-network-guard"]


def test_network_guard_denies_outbound_ip_but_allows_loopback():
    import socket

    saved_connect = socket.socket.connect
    saved_connect_ex = socket.socket.connect_ex
    saved_sendto = socket.socket.sendto
    saved_sendmsg = socket.socket.sendmsg
    # The guard also replaces these module-level functions, so they must be
    # restored or its deny-by-default resolution leaks into every later test.
    saved_resolvers = {
        name: getattr(socket, name)
        for name in (
            "getaddrinfo",
            "gethostbyname",
            "gethostbyname_ex",
            "gethostbyaddr",
            "getnameinfo",
        )
    }
    try:
        # Install recorders as the real operations so allowed addresses fall
        # through to them instead of touching the network; the guard source
        # captures these recorders when it runs.
        recorded: list = []
        socket.socket.connect = lambda self, address: recorded.append(address)
        socket.socket.connect_ex = lambda self, address: recorded.append(address)
        socket.socket.sendto = lambda self, data, *args: recorded.append(args[-1])
        socket.socket.sendmsg = (
            lambda self, *args: recorded.append(args[3] if len(args) >= 4 else None)
        )
        exec(runner.NETWORK_GUARD_SOURCE, {})

        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            with pytest.raises(OSError, match="denies outbound network"):
                probe.connect(("93.184.216.34", 80))
            with pytest.raises(OSError, match="denies outbound network"):
                probe.connect_ex(("8.8.8.8", 53))
            # A connectionless UDP datagram to a public resolver is denied even
            # though it never calls connect().
            with pytest.raises(OSError, match="denies outbound network"):
                udp.sendto(b"x", ("8.8.8.8", 53))
            with pytest.raises(OSError, match="denies outbound network"):
                udp.sendmsg([b"x"], [], 0, ("8.8.8.8", 53))
            # Loopback by address and by name fall through to the recorders.
            probe.connect(("127.0.0.1", 12345))
            probe.connect(("localhost", 12345))
            udp.sendto(b"x", ("127.0.0.1", 12345))
        finally:
            probe.close()
            udp.close()
        assert recorded == [
            ("127.0.0.1", 12345),
            ("localhost", 12345),
            ("127.0.0.1", 12345),
        ]
    finally:
        socket.socket.connect = saved_connect
        socket.socket.connect_ex = saved_connect_ex
        socket.socket.sendto = saved_sendto
        socket.socket.sendmsg = saved_sendmsg
        for name, original in saved_resolvers.items():
            setattr(socket, name, original)


def test_network_guard_blocks_name_resolution_before_any_dns_query_leaves():
    """The connect() block alone still leaked an external DNS query.

    ``socket.create_connection`` — and therefore urllib, http.client and
    requests — resolves the host first, so a guard that watched only the
    connection would refuse the TCP handshake *after* the resolver had already
    been asked about the name.
    """

    import socket

    resolvers = (
        "getaddrinfo",
        "gethostbyname",
        "gethostbyname_ex",
        "gethostbyaddr",
        "getnameinfo",
    )
    saved = {name: getattr(socket, name) for name in resolvers}
    saved_connect = socket.socket.connect
    try:
        resolved: list = []
        socket.getaddrinfo = lambda host, *args, **kwargs: (
            resolved.append(host)
            or saved["getaddrinfo"](host, *args, **kwargs)
        )
        exec(runner.NETWORK_GUARD_SOURCE, {})

        # The whole resolution surface is covered, forward and reverse: a
        # notebook that reached any of these would emit an external query.
        for attempt in (
            lambda: socket.create_connection(("example.com", 80), timeout=0.1),
            lambda: socket.getaddrinfo("example.com", 80),
            lambda: socket.gethostbyname("example.com"),
            lambda: socket.gethostbyname_ex("example.com"),
            lambda: socket.gethostbyaddr("93.184.216.34"),
            lambda: socket.getnameinfo(("93.184.216.34", 80), 0),
        ):
            with pytest.raises(OSError, match="denies outbound network"):
                attempt()
        # No external name ever reached the recorder underneath the guard.
        assert resolved == []

        # socket.getaddrinfo is a Python-level wrapper, so it also takes its
        # target by keyword.  Reading only positional arguments left the target
        # unseen and the call resolved freely — the same leak, one call shape
        # over.  A shape carrying no recognisable target is refused outright.
        for keyword_attempt in (
            lambda: socket.getaddrinfo(host="example.com", port=80),
            lambda: socket.getaddrinfo(host="example.com"),
            lambda: socket.getaddrinfo(port=80),
        ):
            with pytest.raises(OSError, match="denies outbound network"):
                keyword_attempt()
        assert resolved == []

        def guard_allows(*args, **kwargs) -> bool:
            """Whether the guard let the call through to the resolver.

            What the resolver then answers is the platform's business: a
            loopback alias such as ``localhost.localdomain`` is a Linux
            ``/etc/hosts`` convention and does not resolve everywhere.  Only a
            refusal by the guard itself counts as denied.
            """

            try:
                socket.getaddrinfo(*args, **kwargs)
            except OSError as exc:
                return "denies outbound network" not in str(exc)
            return True

        # Loopback resolution still works, so Jupyter's own transport and any
        # local server a notebook starts keep functioning.  DNS names are
        # case-insensitive and getaddrinfo accepts bytes, so those spellings of
        # loopback must not be refused.
        for allowed in (
            ("localhost", 0),
            ("LOCALHOST", 0),
            ("Localhost.", 0),
            (b"localhost", 0),
            (b"127.0.0.1", 0),
            ("localhost.localdomain", 0),
            ("127.0.0.1", 0),
            ("::1", 0),
            (None, 0),
        ):
            assert guard_allows(*allowed), allowed
        assert guard_allows(host=None, port=0)
        assert socket.getnameinfo(("127.0.0.1", 0), 0)

        # A name that merely *starts* with "localhost" is still a public name.
        for public in ("localhost.evil.example", b"example.com", "localhostage.example"):
            with pytest.raises(OSError, match="denies outbound network"):
                socket.getaddrinfo(public, 0)
    finally:
        for name, original in saved.items():
            setattr(socket, name, original)
        socket.socket.connect = saved_connect


def test_network_guard_installs_where_sendmsg_does_not_exist():
    """``socket.sendmsg`` is Unix-only; its absence must not fail the notebook.

    The guard is cell 0, so an AttributeError while installing it aborts the
    whole notebook rather than merely leaving one hook unset.
    """

    import socket
    import sys
    import types

    class _FakeSocketType:
        connect = staticmethod(lambda self, address: None)
        connect_ex = staticmethod(lambda self, address: 0)
        sendto = staticmethod(lambda self, data, *args: None)
        # deliberately no sendmsg

    fake = types.SimpleNamespace(
        AF_INET=socket.AF_INET,
        AF_INET6=socket.AF_INET6,
        socket=_FakeSocketType,
        getaddrinfo=lambda host, *args, **kwargs: [],
        gethostbyname=lambda hostname: "127.0.0.1",
        # gethostbyname_ex/gethostbyaddr/getnameinfo deliberately absent too:
        # every optional hook is installed only where the platform has it.
    )
    saved = sys.modules["socket"]
    sys.modules["socket"] = fake  # type: ignore[assignment]
    try:
        exec(runner.NETWORK_GUARD_SOURCE, {})
    finally:
        sys.modules["socket"] = saved
    assert not hasattr(_FakeSocketType, "sendmsg")
    assert not hasattr(fake, "gethostbyaddr")
    # Everything the platform does provide is still guarded.
    with pytest.raises(OSError, match="denies outbound network"):
        fake.getaddrinfo("example.com", 80)
    with pytest.raises(OSError, match="denies outbound network"):
        fake.gethostbyname("example.com")
    with pytest.raises(OSError, match="denies outbound network"):
        _FakeSocketType.connect(
            types.SimpleNamespace(family=socket.AF_INET), ("93.184.216.34", 80)
        )


def test_kernel_receives_the_isolated_environment_and_the_override(
    monkeypatch, tmp_path
):
    nbformat = pytest.importorskip("nbformat")
    pytest.importorskip("nbclient")
    pytest.importorskip("ipykernel")

    notebook = nbformat.v4.new_notebook()
    parameters = nbformat.v4.new_code_cell("FAST_SMOKE = False")
    parameters.metadata["tags"] = [runner.PARAMETERS_TAG]
    notebook.cells = [
        parameters,
        nbformat.v4.new_code_cell(
            "import matplotlib\n"
            "assert matplotlib.get_backend().lower() == 'agg', "
            "matplotlib.get_backend()\n"
            "assert FAST_SMOKE is True"
        ),
    ]
    notebook_path = tmp_path / "kernel_contract.ipynb"
    nbformat.write(notebook, notebook_path)

    # The kernel must see Agg even when the invoking environment disagrees.
    monkeypatch.setenv("MPLBACKEND", "pdf")
    elapsed = runner._run_with_budget(
        notebook_path,
        cell_timeout_s=120,
        budget_s=240,
        fast_smoke=True,
    )
    assert elapsed > 0.0


def test_the_budget_kills_a_hung_notebook(tmp_path):
    nbformat = pytest.importorskip("nbformat")
    pytest.importorskip("nbclient")
    pytest.importorskip("ipykernel")

    notebook = nbformat.v4.new_notebook()
    notebook.cells = [
        nbformat.v4.new_code_cell("import time\ntime.sleep(600)"),
    ]
    notebook_path = tmp_path / "hung.ipynb"
    nbformat.write(notebook, notebook_path)

    start = time.perf_counter()
    with pytest.raises(SystemExit, match="whole-notebook budget"):
        runner._run_with_budget(
            notebook_path,
            cell_timeout_s=120,
            budget_s=5,
            fast_smoke=False,
        )
    # The per-cell timeout (120 s) never fires; the parent's budget does.
    assert time.perf_counter() - start < 60.0
