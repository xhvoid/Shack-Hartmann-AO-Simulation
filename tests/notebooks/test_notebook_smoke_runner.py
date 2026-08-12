"""AO-REF-019 smoke-runner contract: kernel isolation, budget, injection.

The static tests always run; the two integration tests spawn a real kernel
and therefore skip in environments without the ``notebook-test`` extra
(``nbclient`` + ``ipykernel``), exactly like the notebook CI lanes.
"""

from __future__ import annotations

import contextlib
import importlib.util
import signal
import subprocess
import sys
import time
import types
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


def _guarded_socket_methods() -> tuple[str, ...]:
    """The socket methods the guard patches that *this* platform actually has.

    ``socket.socket.sendmsg`` is a Unix-only API.  These tests exec the guard
    against the real socket module, so they have to save and restore exactly the
    methods that exist here: reading ``socket.socket.sendmsg`` unconditionally
    raises AttributeError on Windows before the test reaches its first
    assertion, and assigning a replacement there would be worse still — it would
    leave a ``sendmsg`` on a class that never had one, so later code would
    believe the platform supports a call it cannot make.  The list is recomputed
    on every call rather than snapshotted at import, which is what lets the
    leak check below notice a hook that synthesised the attribute.
    """

    import socket

    return tuple(
        name
        for name in ("connect", "connect_ex", "sendto", "sendmsg")
        if hasattr(socket.socket, name)
    )


@contextlib.contextmanager
def _sendmsg_hidden_from_socket():
    """Make ``socket.socket.sendmsg`` absent the way it is absent on Windows.

    The attribute is inherited from the C ``_socket.socket`` base, so it cannot
    simply be deleted; a descriptor that raises AttributeError on lookup gives
    ``hasattr`` and ``getattr(..., default)`` exactly the answer a platform
    without the syscall gives, and those are the only two questions this code
    asks.  Without such a stand-in the Windows portability of these tests could
    be asserted only on Windows, so the suite would keep passing here while
    failing there — which is how the unconditional accesses survived review.
    """

    import socket

    class _absent:
        def __get__(self, instance, owner=None):
            raise AttributeError("sendmsg")

    own = vars(socket.socket).get("sendmsg")
    had_own = "sendmsg" in vars(socket.socket)
    socket.socket.sendmsg = _absent()
    try:
        yield
    finally:
        if had_own:
            socket.socket.sendmsg = own
        else:
            del socket.socket.sendmsg


def test_network_guard_denies_outbound_ip_but_allows_loopback():
    import socket

    guarded = _guarded_socket_methods()
    saved_methods = {name: getattr(socket.socket, name) for name in guarded}
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
        if "sendmsg" in guarded:
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
            # sendmsg exists only where the platform has the syscall; the rest
            # of this contract is checked everywhere regardless.
            if "sendmsg" in guarded:
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
        for name, original in saved_methods.items():
            setattr(socket.socket, name, original)
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
    # The guard replaces every one of these that the platform provides;
    # restoring only some leaves a deny-by-default hook installed for the rest
    # of the pytest session, and reading one the platform lacks fails the test
    # outright rather than the code it is meant to be checking.
    saved_methods = {
        name: getattr(socket.socket, name) for name in _guarded_socket_methods()
    }
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
        for name, original in saved_methods.items():
            setattr(socket.socket, name, original)


def test_the_guard_tests_leave_no_hook_installed_in_this_process():
    """Every socket entry point the guard patches must be restored.

    These tests exec the guard against the *real* socket module, so a hook left
    behind denies traffic for every later test in the same process.  The method
    list is the one this platform actually has, recomputed here: a hook that
    invented ``sendmsg`` on a platform without it appears in that list and is
    caught by the same assertion, so nothing escapes by being unexpected.
    """

    import socket

    for name in (
        "getaddrinfo",
        "gethostbyname",
        "gethostbyname_ex",
        "gethostbyaddr",
        "getnameinfo",
    ):
        module_level = getattr(socket, name)
        assert module_level.__module__ in ("socket", "_socket"), (name, module_level)
    for name in _guarded_socket_methods():
        method = getattr(socket.socket, name)
        assert not isinstance(method, types.FunctionType), (name, method)


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


def test_the_guard_tests_themselves_run_where_socket_sendmsg_is_absent():
    """The suite must pass on Windows, not merely the code it exercises.

    The runtime guard already installs where ``socket.sendmsg`` is missing, but
    the tests above saved, replaced and asserted on that attribute
    unconditionally, so on Windows they raised AttributeError and the offline
    contract went unchecked on the one platform whose absent syscall the guard
    was made portable for.  Running them here with the attribute hidden is the
    only way to hold that from a Unix machine; each still checks everything that
    is not sendmsg-specific, because a whole test skipped for one assertion is a
    contract nobody verifies.
    """

    import socket

    platform_has_sendmsg = hasattr(socket.socket, "sendmsg")
    with _sendmsg_hidden_from_socket():
        assert "sendmsg" not in _guarded_socket_methods()
        test_network_guard_denies_outbound_ip_but_allows_loopback()
        test_network_guard_blocks_name_resolution_before_any_dns_query_leaves()
        test_the_guard_tests_leave_no_hook_installed_in_this_process()

    # The stand-in is removed again, so the rest of the session sees whatever
    # this platform really provides instead of a descriptor that refuses to be
    # looked up at all.
    assert hasattr(socket.socket, "sendmsg") is platform_has_sendmsg


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


def test_network_isolation_is_required_by_default():
    """The default must be the enforced contract, not the tripwire.

    A lane that quietly degraded to the in-kernel guard would report AO-REF-019
    offline execution while a ``!curl`` cell, a ``%pip install``, or a direct
    ``_socket`` call reached the network unimpeded.  CI passes no flag, so the
    default is what CI enforces.
    """

    assert set(runner.NETWORK_ISOLATION_MODES) == {"required", "auto", "off"}
    # The CI lanes invoke the runner with no isolation flag at all.
    parsed = runner.build_parser().parse_args(["--class", "fast"])
    assert parsed.network_isolation == "required" == runner.DEFAULT_NETWORK_ISOLATION


def test_required_isolation_refuses_where_no_namespace_is_available(monkeypatch, capsys):
    monkeypatch.setattr(runner, "_network_namespace_prefix", lambda: None)

    with pytest.raises(SystemExit, match="Network isolation is unavailable"):
        runner._resolve_network_isolation("required")

    # 'auto' is the documented escape hatch, and it must say what was lost
    # rather than pass silently.
    assert runner._resolve_network_isolation("auto") == []
    assert "NOT enforced" in capsys.readouterr().out

    # 'off' never even probes.
    monkeypatch.setattr(
        runner,
        "_network_namespace_prefix",
        lambda: (_ for _ in ()).throw(AssertionError("probed with isolation off")),
    )
    assert runner._resolve_network_isolation("off") == []


def test_an_available_namespace_is_used_by_every_mode_that_allows_it(monkeypatch):
    prefix = ["/usr/bin/unshare", "--user", "--map-root-user", "--net", "--"]
    monkeypatch.setattr(runner, "_network_namespace_prefix", lambda: list(prefix))

    for mode in ("required", "auto"):
        assert runner._resolve_network_isolation(mode) == prefix


_FAKE_UNSHARE = "/usr/bin/unshare"
_FAKE_IP = "/usr/sbin/ip"
_FAKE_SUDO = "/usr/bin/sudo"
_FAKE_NSENTER = "/usr/bin/nsenter"

# Never offered, and named here so the test below can say so. A network
# namespace without a user namespace does not confine a process holding
# CAP_SYS_ADMIN over it: setns(2) lets it reopen the outer namespace and step
# back onto the host network. The sudo variant is worse, not better.
_PRIVILEGED_NET = [_FAKE_UNSHARE, "--net", "--"]
_PRIVILEGED_SUDO_NET = [_FAKE_SUDO, "-n", _FAKE_UNSHARE, "--net", "--"]

_USER_NET = [_FAKE_UNSHARE, "--user", "--map-root-user", "--net", "--"]
_SUDO_NET = [
    _FAKE_SUDO,
    "-n",
    _FAKE_UNSHARE,
    "--user",
    "--map-root-user",
    "--net",
    "--",
]

# What `ip -o link show` prints inside a fresh namespace, and what it prints
# where the unshare did not actually take: the runner parses these, so the
# fakes are the real shape rather than a convenient one.
_LOOPBACK_ONLY_LINKS = (
    "1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN mode "
    "DEFAULT group default qlen 1000\\    link/loopback 00:00:00:00:00:00 brd "
    "00:00:00:00:00:00\n"
)
_HOST_NETWORK_LINKS = _LOOPBACK_ONLY_LINKS + (
    "2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP mode "
    "DEFAULT group default qlen 1000\\    link/ether 02:42:ac:11:00:02 brd "
    "ff:ff:ff:ff:ff:ff\n"
)


def _fake_linux_namespace_environment(
    monkeypatch,
    *,
    links_seen_by,
    sudo=_FAKE_SUDO,
    sudo_needs_a_password=False,
    escape_succeeds_for=(),
    nsenter=_FAKE_NSENTER,
):
    """Run the probe's Linux decision path against recorded fakes.

    ``links_seen_by`` maps a prefix (as a tuple) to the ``ip -o link show``
    output that prefix produces; a prefix that is absent from it probes as a
    failure, which is exactly what a refused namespace looks like from here.
    ``escape_succeeds_for`` names the prefixes whose namespace can still be
    left through setns — the condition that makes a loopback-only namespace an
    illusion, and the one a bare ``unshare --net`` actually satisfies.

    Nothing about a live namespace can be checked from macOS — there is no
    unshare(1) to run — so what these fakes hold is the decision: which forms
    are offered, in which order, which are skipped, and what the probe accepts
    as evidence.  The namespace itself stays covered by the Linux-only tests
    at the end of this module, which is where it can be created for real.
    """

    executed: list[list[str]] = []
    escapes = {tuple(prefix) for prefix in escape_succeeds_for}

    def fake_run(command, **kwargs):
        command = list(command)
        executed.append(command)
        if command[1:] == ["-n", "true"]:
            return subprocess.CompletedProcess(
                command,
                1 if sudo_needs_a_password else 0,
                "",
                "sudo: a password is required\n" if sudo_needs_a_password else "",
            )
        # The probe carries the outer namespace path as an argument, so the
        # trailing three fields are the script, ``sh`` and that path.
        assert command[-5:-3] == ["sh", "-c"], command
        assert command[-1].startswith("/proc/"), command
        prefix = tuple(command[:-5])
        links = links_seen_by.get(prefix)
        if links is None:
            return subprocess.CompletedProcess(
                command, 1, "", "unshare: unshare failed: Operation not permitted\n"
            )
        verdict = "ESCAPE_SUCCEEDED\n" if prefix in escapes else "ESCAPE_REFUSED\n"
        return subprocess.CompletedProcess(command, 0, links + verdict, "")

    tools = {"unshare": _FAKE_UNSHARE, "ip": _FAKE_IP}
    if sudo is not None:
        tools["sudo"] = sudo
    if nsenter is not None:
        tools["nsenter"] = nsenter
    monkeypatch.setattr(runner, "shutil", types.SimpleNamespace(which=tools.get))
    monkeypatch.setattr(
        runner,
        "subprocess",
        types.SimpleNamespace(
            run=fake_run, SubprocessError=subprocess.SubprocessError
        ),
    )
    monkeypatch.setattr(
        runner,
        "sys",
        types.SimpleNamespace(platform="linux", executable=sys.executable),
    )
    return executed


def test_a_stock_ubuntu_24_04_runner_reaches_a_namespace_through_sudo(monkeypatch):
    """The configured hosted runner refuses the unelevated form.

    ubuntu-latest is Ubuntu 24.04, which ships
    kernel.apparmor_restrict_unprivileged_userns=1: AppArmor denies capabilities
    inside an *unprivileged* user namespace, so the ordinary form fails and the
    required notebook lanes had no namespace at all.  Sudo makes the same
    unshare privileged, which the restriction does not cover — and because that
    form still enters a child user namespace, it confines the kernel instead of
    merely relocating it.
    """

    executed = _fake_linux_namespace_environment(
        monkeypatch, links_seen_by={tuple(_SUDO_NET): _LOOPBACK_ONLY_LINKS}
    )

    assert runner._network_namespace_prefix() == _SUDO_NET
    # The unelevated form was actually tried before sudo was asked for anything.
    attempted = [command[: command.index("sh")] for command in executed[:1]]
    assert attempted == [_USER_NET]
    assert executed[1] == [_FAKE_SUDO, "-n", "true"]
    assert executed[2][: len(_SUDO_NET)] == _SUDO_NET


def test_the_probed_forms_are_ordered_least_privileged_first(monkeypatch):
    _fake_linux_namespace_environment(monkeypatch, links_seen_by={})

    assert list(runner._namespace_prefix_candidates()) == [_USER_NET, _SUDO_NET]


def test_a_network_namespace_without_a_user_namespace_is_never_offered(monkeypatch):
    """A bare ``unshare --net`` is not an offline sandbox and is not proposed.

    setns(2) admits a process to any network namespace it holds CAP_SYS_ADMIN
    over in that namespace's owning user namespace.  Under ``unshare --net``
    alone — and under ``sudo unshare --net``, which holds more capability, not
    less — notebook code keeps exactly that, so it can reopen
    ``/proc/<pid>/ns/net`` and step back onto the host network.  The interface
    listing cannot see this: it reports where the process started, not where it
    may go.  Entering a child user namespace is what drops the capability, so
    every offered form asks for one.
    """

    _fake_linux_namespace_environment(monkeypatch, links_seen_by={})
    offered = list(runner._namespace_prefix_candidates())

    for form in (_PRIVILEGED_NET, _PRIVILEGED_SUDO_NET):
        assert form not in offered
    for form in offered:
        assert "--user" in form and "--map-root-user" in form, form


def test_a_namespace_that_can_be_left_again_is_not_used(monkeypatch):
    """Confinement is observed, not inferred from the flags that were passed.

    A prefix whose namespace holds loopback and nothing else is still useless if
    the process inside it can rejoin the outer one, so the probe attempts
    exactly that and requires the attempt to fail.  This is the check that would
    have caught the privileged form on its own terms rather than by argument.
    """

    _fake_linux_namespace_environment(
        monkeypatch,
        links_seen_by={
            tuple(_USER_NET): _LOOPBACK_ONLY_LINKS,
            tuple(_SUDO_NET): _LOOPBACK_ONLY_LINKS,
        },
        escape_succeeds_for=(_USER_NET, _SUDO_NET),
    )

    assert runner._network_namespace_prefix() is None
    with pytest.raises(SystemExit, match="Network isolation is unavailable"):
        runner._resolve_network_isolation("required")


def test_without_nsenter_confinement_cannot_be_observed_so_nothing_is_offered(
    monkeypatch,
):
    """The escape attempt is the evidence, so its absence is a refusal.

    Accepting a prefix whose confinement could not be tested would put the
    offline contract back on an argument, which is the thing that failed here.
    """

    _fake_linux_namespace_environment(
        monkeypatch, links_seen_by={tuple(_USER_NET): _LOOPBACK_ONLY_LINKS}, nsenter=None
    )

    assert list(runner._namespace_prefix_candidates()) == []
    assert runner._network_namespace_prefix() is None


def test_a_form_that_needs_no_elevation_never_asks_sudo_for_anything(monkeypatch):
    """Ordering is the whole point of the list, so it is asserted, not assumed.

    Where the unprivileged user namespace is available the kernel keeps the
    invoking user's credentials; reaching for sudo there would elevate for
    nothing and run the kernel as root.
    """

    executed = _fake_linux_namespace_environment(
        monkeypatch, links_seen_by={tuple(_USER_NET): _LOOPBACK_ONLY_LINKS}
    )

    assert runner._network_namespace_prefix() == _USER_NET
    assert len(executed) == 1
    assert _FAKE_SUDO not in executed[0]


def test_sudo_is_not_offered_when_it_cannot_elevate_without_asking(monkeypatch):
    """A sudo that wants a password is the same answer as no sudo at all.

    Neither can be turned into a namespace by a CI step nobody is watching, and
    offering the form anyway would spend the probe budget proving it.
    """

    executed = _fake_linux_namespace_environment(
        monkeypatch, links_seen_by={}, sudo_needs_a_password=True
    )
    assert list(runner._namespace_prefix_candidates()) == [_USER_NET]
    assert [_FAKE_SUDO, "-n", "true"] in executed
    assert all(command[0] != _FAKE_SUDO for command in executed[1:])

    absent = _fake_linux_namespace_environment(
        monkeypatch, links_seen_by={}, sudo=None
    )
    assert list(runner._namespace_prefix_candidates()) == [_USER_NET]
    assert absent == []


def test_a_probe_that_still_sees_the_host_network_is_not_used(monkeypatch):
    """A prefix is evidence only if the namespace it made holds nothing else.

    A probe that merely exited zero proves nothing: an unshare that silently did
    not take, or a sudo rule that ran the command outside a namespace, would
    otherwise be adopted and the lane would report an offline contract with a
    route to the outside still in place.
    """

    _fake_linux_namespace_environment(
        monkeypatch,
        links_seen_by={
            tuple(_USER_NET): _HOST_NETWORK_LINKS,
            tuple(_SUDO_NET): _HOST_NETWORK_LINKS,
        },
    )

    assert runner._network_namespace_prefix() is None
    with pytest.raises(SystemExit, match="Network isolation is unavailable"):
        runner._resolve_network_isolation("required")


def test_required_isolation_still_refuses_when_not_even_sudo_isolates(monkeypatch):
    _fake_linux_namespace_environment(monkeypatch, links_seen_by={})

    assert runner._network_namespace_prefix() is None
    with pytest.raises(SystemExit, match="Network isolation is unavailable"):
        runner._resolve_network_isolation("required")


def test_only_a_sudo_prefix_yields_something_to_escalate_a_signal_through():
    assert runner._sudo_escalation(_SUDO_NET) == [_FAKE_SUDO, "-n"]
    assert runner._sudo_escalation(_USER_NET) == []
    assert runner._sudo_escalation(_PRIVILEGED_NET) == []
    assert runner._sudo_escalation([]) == []


def test_the_budget_kill_is_reissued_through_sudo_for_a_root_owned_group(monkeypatch):
    """An unprivileged parent cannot signal the root group sudo started.

    kill(2) delivers a signal only when the sender's real or effective uid
    matches the target's real or saved uid, and everything behind sudo has both
    set to root, so killpg raises EPERM.  Left unhandled the budget would report
    PermissionError instead of the budget message and the notebook it was meant
    to bound would keep running.
    """

    refused: list[tuple[int, int]] = []
    escalated: list[list[str]] = []
    waited: list[str] = []

    def refuse_killpg(process_group, signal_number):
        refused.append((process_group, signal_number))
        raise PermissionError(1, "Operation not permitted")

    def fake_run(command, **kwargs):
        escalated.append(list(command))
        return subprocess.CompletedProcess(list(command), 0, "", "")

    monkeypatch.setattr(
        runner, "os", types.SimpleNamespace(name="posix", killpg=refuse_killpg)
    )
    monkeypatch.setattr(
        runner,
        "subprocess",
        types.SimpleNamespace(
            run=fake_run, SubprocessError=subprocess.SubprocessError
        ),
    )
    process = types.SimpleNamespace(
        pid=4321, wait=lambda: waited.append("waited"), kill=lambda: None
    )

    runner._kill_process_group(process, [_FAKE_SUDO, "-n"])

    assert refused == [(4321, signal.SIGKILL)]
    assert escalated and escalated[0][:2] == [_FAKE_SUDO, "-n"]
    assert "4321" in escalated[0]
    # The parent still reaps the child, or the budget message would race the
    # process it just ended.
    assert waited == ["waited"]

    # With nothing to escalate through, EPERM is not swallowed: a budget that
    # silently failed to kill is a budget that was never enforced.
    escalated.clear()
    with pytest.raises(PermissionError):
        runner._kill_process_group(process, [])
    assert escalated == []


def test_a_successful_killpg_still_gets_the_privileged_pass(monkeypatch):
    """Success from killpg does not mean the group is gone.

    kill(2) reports success when the signal reached *at least one* member of the
    group.  Behind sudo the group holds the signalable sudo process and the root
    descendants it started, so killing sudo alone returns success while the
    kernel keeps running and the notebook keeps executing in it.  Escalating
    only on PermissionError therefore missed exactly the case the escalation
    exists for, so the privileged pass runs whenever the group was started
    privileged.
    """

    escalated: list[list[str]] = []
    waited: list[str] = []

    monkeypatch.setattr(
        runner,
        "os",
        types.SimpleNamespace(name="posix", killpg=lambda pgid, sig: None),
    )
    monkeypatch.setattr(
        runner,
        "subprocess",
        types.SimpleNamespace(
            run=lambda command, **kwargs: escalated.append(list(command)),
            SubprocessError=subprocess.SubprocessError,
        ),
    )
    process = types.SimpleNamespace(
        pid=4321, wait=lambda: waited.append("waited"), kill=lambda: None
    )

    runner._kill_process_group(process, [_FAKE_SUDO, "-n"])
    assert escalated and escalated[0][:2] == [_FAKE_SUDO, "-n"]
    assert "4321" in escalated[0]
    assert waited == ["waited"]

    # An unprivileged group is not signalled twice: there is nothing the second
    # pass could reach that the first did not.
    escalated.clear()
    runner._kill_process_group(process, [])
    assert escalated == []


def test_the_budget_hands_the_kill_the_escalation_its_prefix_implies(monkeypatch, tmp_path):
    handed: list[list[str]] = []

    class _NeverExits:
        pid = 9999

        def wait(self, timeout=None):
            if timeout is not None:
                raise subprocess.TimeoutExpired("runner", timeout)
            return 0

    monkeypatch.setattr(
        runner,
        "subprocess",
        types.SimpleNamespace(
            Popen=lambda *args, **kwargs: _NeverExits(),
            TimeoutExpired=subprocess.TimeoutExpired,
            SubprocessError=subprocess.SubprocessError,
        ),
    )
    monkeypatch.setattr(
        runner,
        "_kill_process_group",
        lambda process, escalation: handed.append(escalation),
    )

    with pytest.raises(SystemExit, match="whole-notebook budget"):
        runner._run_with_budget(
            tmp_path / "study.ipynb",
            cell_timeout_s=90,
            budget_s=1,
            fast_smoke=False,
            isolation_prefix=list(_SUDO_NET),
        )
    assert handed == [[_FAKE_SUDO, "-n"]]


def test_the_runner_command_wraps_the_runner_inside_the_namespace(tmp_path):
    notebook = tmp_path / "study.ipynb"
    prefix = ["/usr/bin/unshare", "--user", "--map-root-user", "--net", "--"]

    isolated = runner._runner_command(
        notebook,
        cell_timeout_s=90,
        fast_smoke=True,
        isolation_prefix=prefix,
    )
    plain = runner._runner_command(
        notebook,
        cell_timeout_s=90,
        fast_smoke=True,
        isolation_prefix=[],
    )

    assert isolated[: len(prefix)] == prefix
    # Loopback is brought up inside the namespace, or the kernel's own ZMQ
    # channels could not connect; the runner then replaces the shell, so no
    # argument is ever re-parsed and a notebook path may contain anything.
    assert isolated[len(prefix) : len(prefix) + 3] == ["sh", "-c", runner._NAMESPACE_SHELL]
    assert "ip link set lo up" in runner._NAMESPACE_SHELL
    assert isolated[len(prefix) + 3 :] == plain
    assert plain[0] == sys.executable
    assert "--single" in plain and str(notebook) in plain and "--fast-smoke" in plain


@pytest.mark.skipif(sys.platform != "linux", reason="network namespaces are a Linux facility")
def test_the_namespace_probe_reports_a_loopback_only_namespace():
    prefix = runner._network_namespace_prefix()
    if prefix is None:
        pytest.skip("unprivileged user namespaces are not permitted here")
    listing = __import__("subprocess").run(
        [*prefix, "sh", "-c", "ip link set lo up && ip -o link show"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    interfaces = {
        line.split(":", 2)[1].strip().split("@", 1)[0]
        for line in listing.splitlines()
        if line.count(":") >= 2
    }
    assert interfaces == {"lo"}


@pytest.mark.skipif(sys.platform != "linux", reason="network namespaces are a Linux facility")
def test_the_kernel_really_runs_with_loopback_only(tmp_path):
    """The contract is about the kernel, not about the runner that starts it.

    Asserting on the interfaces the kernel can see tests the layer the in-kernel
    guard cannot provide: this holds for a subprocess, a C extension, and a
    direct ``_socket`` call, none of which the guard sees.
    """

    nbformat = pytest.importorskip("nbformat")
    pytest.importorskip("nbclient")
    pytest.importorskip("ipykernel")
    prefix = runner._network_namespace_prefix()
    if prefix is None:
        pytest.skip("unprivileged user namespaces are not permitted here")

    notebook = nbformat.v4.new_notebook()
    notebook.cells = [
        nbformat.v4.new_code_cell(
            "import socket, subprocess, sys\n"
            "names = sorted(name for _, name in socket.if_nameindex())\n"
            "assert names == ['lo'], names\n"
            # A subprocess walks past the in-kernel guard and must still find
            # nothing but loopback.
            "child = subprocess.run(\n"
            "    [sys.executable, '-c',\n"
            "     'import socket; print(sorted(n for _, n in socket.if_nameindex()))'],\n"
            "    capture_output=True, text=True, check=True)\n"
            "assert child.stdout.strip() == \"['lo']\", child.stdout\n"
            # Loopback still works, so a notebook may serve or connect locally.
            "server = socket.socket()\n"
            "server.bind(('127.0.0.1', 0))\n"
            "server.listen(1)\n"
            "client = socket.create_connection(server.getsockname(), 5)\n"
            "client.close()\n"
            "server.close()\n"
        )
    ]
    notebook_path = tmp_path / "isolation_contract.ipynb"
    nbformat.write(notebook, notebook_path)

    assert (
        runner._run_with_budget(
            notebook_path,
            cell_timeout_s=120,
            budget_s=300,
            fast_smoke=False,
            isolation_prefix=prefix,
        )
        > 0.0
    )
