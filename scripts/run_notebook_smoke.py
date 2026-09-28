#!/usr/bin/env python3
"""Execute canonical notebooks under the AO-REF-019 smoke contract.

Each notebook is executed by a dedicated runner subprocess in a fresh
temporary working directory (never the repository root).  The parent enforces
the whole-notebook wall-clock budget by killing the runner's process group
when the budget expires, so a hung cell, a stuck import, or an unresponsive
kernel cannot outlive it; the per-cell timeout is enforced inside ``nbclient``.
The kernel environment (``MPLBACKEND=Agg``) is passed explicitly through
``NotebookClient.execute`` into ``KernelManager.start_kernel`` — ``nbclient``
has no ``env`` trait, so a constructor argument would be silently dropped.
The runner imports only the installed package, so it validates that a
notebook runs from a built, non-editable wheel without source-tree imports
or hidden local files.

Offline execution is enforced at two levels, because one of them is not
enough.  The outer level is the real one: the runner subprocess and the kernel
it starts are placed in their own network namespace containing nothing but
loopback, so *no* code they run can reach the network — a ``!curl`` cell, a
``%pip install``, a ``subprocess.run``, a C extension, or a direct call into
the private ``_socket`` module.  Loopback is brought up inside the namespace
because Jupyter's own ZMQ channels use it.  The inner level is an injected
first cell that denies outbound IPv4/IPv6 connections and non-loopback name
resolution inside the kernel, which turns an attempted access into a clear
Python error naming the address instead of an opaque "Network is unreachable"
from somewhere deep in a library.

Namespace isolation is a Linux facility, so ``--network-isolation`` states what
to do when it is unavailable.  The default, ``required``, refuses to run: a
notebook lane that quietly degraded to the in-kernel tripwire would report a
contract it did not enforce.  ``auto`` runs anyway with the tripwire alone and
says so; ``off`` disables the namespace entirely.  Continuous integration runs
on Linux and therefore gets the real thing without asking for it.

Usage::

    python scripts/run_notebook_smoke.py NOTEBOOK [NOTEBOOK ...]
    python scripts/run_notebook_smoke.py --class fast   # from the manifest
    python scripts/run_notebook_smoke.py --class slow --fast-smoke
    python scripts/run_notebook_smoke.py --class fast --network-isolation auto

``--class`` selects every canonical notebook whose manifest execution class
matches (``fast`` is the default CI selection).  ``--fast-smoke`` injects
``FAST_SMOKE = True`` immediately after each notebook's single
``parameters``-tagged cell, so slow studies run their small representative
parameterization in fast CI while the scheduled lane executes the full study.
Notebooks are executed on a throwaway copy, so the tracked ``.ipynb`` files
and their committed outputs are never modified by the smoke run.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "notebooks" / "notebook_manifest.json"

DEFAULT_CELL_TIMEOUT_S = 120
DEFAULT_NOTEBOOK_BUDGET_S = 600
PARAMETERS_TAG = "parameters"
FAST_SMOKE_OVERRIDE_SOURCE = "FAST_SMOKE = True"
NETWORK_ISOLATION_MODES = ("required", "auto", "off")
DEFAULT_NETWORK_ISOLATION = "required"

# Brings loopback up inside the new namespace and then becomes the runner, so
# the kernel's own ZMQ transport keeps working while nothing else is reachable.
# ``$0``/``$@`` carry the real command, so no argument is ever re-parsed by the
# shell — a notebook path may contain any character a path can contain.
_NAMESPACE_SHELL = 'ip link set lo up && exec "$0" "$@"'

# Run after a candidate has initialized loopback to decide whether it may be
# used. ``$2`` is a caller-owned private file that must remain readable. ``$1``
# is the *outer* network namespace — the one the notebook must not be able to
# return to — so nsenter's refusal to enter it is the observation that a network
# namespace alone would not have produced, and that a bare `unshare --net`
# would have failed.  Printed as a word rather than signalled by exit status,
# because the interface listing has to come back from the same run.
_NAMESPACE_PROBE = (
    'test -r "$2" && ip -o link show && cat /proc/self/status && '
    'if nsenter --net="$1" true 2>/dev/null; '
    "then echo ESCAPE_SUCCEEDED; else echo ESCAPE_REFUSED; fi"
)

# Run by _kill_process_group when the group it must end is owned by root.  The
# process group id arrives as an argument rather than being interpolated, so
# nothing is re-parsed and the call is the same killpg the parent just tried.
# argv[1] is the runner's process group; the rest are the individual
# descendants that live outside it. Both are needed for the same reason the
# unprivileged path needs both.
_REISSUE_KILLPG = (
    "import os, signal, sys\n"
    "try:\n"
    "    os.killpg(int(sys.argv[1]), signal.SIGKILL)\n"
    "except ProcessLookupError:\n"
    # Expected, not exceptional: this pass runs whenever the group was started
    # privileged, so an unprivileged kill that already reaped every member
    # leaves nothing here to signal.
    "    pass\n"
    "for stray in sys.argv[2:]:\n"
    "    try:\n"
    "        os.kill(int(stray), signal.SIGKILL)\n"
    "    except (ProcessLookupError, ValueError):\n"
    "        pass\n"
)


def _descendant_pids(root_pid: int) -> list[int]:
    """Every live descendant of ``root_pid``, transitively.

    Killing the runner's process group is not enough to end a notebook run.
    jupyter_client launches the kernel with ``start_new_session=True``, so the
    kernel is a session and group leader of its own: a signal to the runner's
    group never reaches it, and a budget that killed only the runner left the
    kernel executing the notebook it was supposed to stop.  The kernel is still
    a *descendant*, though, which is what this walks.

    Read from ``ps`` because it is the one process table available on both
    platforms this script runs on without a third-party dependency.  Failure to
    read it returns no descendants rather than raising: the caller has a group
    kill to perform either way, and it reports its own outcome.
    """

    try:
        listing = subprocess.run(
            ["ps", "-Ao", "pid=,ppid="],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if listing.returncode != 0:
        return []
    children: dict[int, list[int]] = {}
    for line in listing.stdout.splitlines():
        fields = line.split()
        if len(fields) != 2:
            continue
        try:
            pid, parent = int(fields[0]), int(fields[1])
        except ValueError:
            continue
        children.setdefault(parent, []).append(pid)
    found: list[int] = []
    seen = {root_pid}
    queue = [root_pid]
    while queue:
        for child in children.get(queue.pop(), ()):
            if child in seen:
                continue
            seen.add(child)
            found.append(child)
            queue.append(child)
    return found

# Injected as the first executed cell so it is active for every real cell.
# The namespace around the process is what actually denies the network; this
# is the layer that makes an attempt legible, turning "Network is unreachable"
# from inside a third-party library into an error naming the address a cell
# asked for.  It also stands alone under ``--network-isolation auto`` on a
# platform with no namespaces.  Three layers are covered, because blocking only
# the last one still leaks: name resolution, forward and reverse, which every
# real client reaches first; connection-oriented calls (connect/connect_ex);
# and connectionless, address-bearing sends (sendto/sendmsg), so a UDP datagram
# cannot slip past either.
NETWORK_GUARD_SOURCE = '''\
import ipaddress as _ipaddress
import socket as _socket


def _install_offline_guard():
    real_connect = _socket.socket.connect
    real_connect_ex = _socket.socket.connect_ex
    ip_families = (_socket.AF_INET, _socket.AF_INET6)

    # The standard loopback aliases: none of these can name a public host, and
    # refusing them would break a notebook for no gain.  Comparison is
    # case-folded because DNS names are case-insensitive, and a trailing root
    # dot is stripped, so "LOCALHOST." is the same name as "localhost".
    loopback_names = frozenset(
        (
            "localhost",
            "localhost.localdomain",
            "localhost4",
            "localhost4.localdomain4",
            "localhost6",
            "localhost6.localdomain6",
        )
    )

    def _host_denied(host):
        # None is a wildcard bind (AI_PASSIVE), and loopback stays reachable so
        # Jupyter's own ZMQ transport keeps working; every other name or
        # address is refused.
        if host is None:
            return False
        if isinstance(host, (bytes, bytearray)):
            # getaddrinfo accepts a bytes host; decode it rather than refuse a
            # loopback name for its type.
            try:
                host = host.decode("ascii")
            except UnicodeDecodeError:
                return True
        if not isinstance(host, str):
            # Anything else is a shape this guard does not understand, so it
            # cannot be shown to be loopback: refuse it.
            return True
        if host.rstrip(".").lower() in loopback_names:
            return False
        try:
            return not _ipaddress.ip_address(host).is_loopback
        except ValueError:
            return True

    def _denied(sock, address):
        if sock.family not in ip_families:
            return False
        if address is None:
            return False
        host = address[0] if isinstance(address, (tuple, list)) else address
        return _host_denied(host)

    def _refuse(address):
        raise OSError(
            "notebook smoke denies outbound network: " + repr(address)
        )

    def connect(self, address):
        if _denied(self, address):
            _refuse(address)
        return real_connect(self, address)

    def connect_ex(self, address):
        if _denied(self, address):
            _refuse(address)
        return real_connect_ex(self, address)

    _socket.socket.connect = connect
    _socket.socket.connect_ex = connect_ex

    # Every real client resolves before it connects, so a guard that watched
    # only connect() still let the query leave the machine.  Cover the whole
    # resolution surface, forward and reverse.  The target is the first
    # positional argument of each of these — but socket.getaddrinfo is a
    # Python-level wrapper, so it also accepts the target by keyword, and
    # reading only args would let getaddrinfo(host=...) resolve freely.
    _unknown_target = object()

    def _guard_resolver(name, keywords, host_of):
        real = getattr(_socket, name, None)
        if real is None:
            return

        def guarded(*args, **kwargs):
            if args:
                target = args[0]
            else:
                target = _unknown_target
                for keyword in keywords:
                    if keyword in kwargs:
                        target = kwargs[keyword]
                        break
            # An unrecognised call shape is refused rather than passed through:
            # a target this guard cannot locate has not been shown to be
            # loopback, and failing open here is how the query escapes.
            if target is _unknown_target:
                _refuse(kwargs)
            host = host_of(target)
            if _host_denied(host):
                _refuse(host)
            return real(*args, **kwargs)

        setattr(_socket, name, guarded)

    def _itself(target):
        return target

    def _sockaddr_host(target):
        if isinstance(target, (tuple, list)) and target:
            return target[0]
        return target

    for _name, _keywords in (
        ("getaddrinfo", ("host",)),
        ("gethostbyname", ("hostname",)),
        ("gethostbyname_ex", ("hostname",)),
        ("gethostbyaddr", ("ip_address",)),
    ):
        _guard_resolver(_name, _keywords, _itself)
    _guard_resolver("getnameinfo", ("sockaddr",), _sockaddr_host)

    # sendto is universal, but sendmsg is a Unix-only API.  Patch each only
    # where it exists, so the guard installs on every platform instead of
    # failing the whole notebook on the one where it is absent.
    real_sendto = getattr(_socket.socket, "sendto", None)
    if real_sendto is not None:

        def sendto(self, data, *args):
            # sendto(data, address) or sendto(data, flags, address): the
            # destination is always the final positional argument.
            address = args[-1] if args else None
            if _denied(self, address):
                _refuse(address)
            return real_sendto(self, data, *args)

        _socket.socket.sendto = sendto

    real_sendmsg = getattr(_socket.socket, "sendmsg", None)
    if real_sendmsg is not None:

        def sendmsg(self, *args):
            # sendmsg(buffers[, ancdata[, flags[, address]]]): a datagram
            # carries its destination as the optional fourth argument.
            address = args[3] if len(args) >= 4 else None
            if _denied(self, address):
                _refuse(address)
            return real_sendmsg(self, *args)

        _socket.socket.sendmsg = sendmsg


_install_offline_guard()
del _install_offline_guard
'''


def _canonical_paths_for_class(execution_class: str) -> list[Path]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return [
        ROOT / entry["path"]
        for entry in manifest["canonical"]
        if entry["execution_class"] == execution_class
    ]


def _kernel_environment() -> dict[str, str]:
    """Environment for the runner subprocess and the kernel it starts."""

    environment = dict(os.environ)
    environment["MPLBACKEND"] = "Agg"
    return environment


def _inject_network_guard(notebook) -> None:
    """Insert the outbound-network guard as the notebook's first cell."""

    import nbformat

    guard = nbformat.v4.new_code_cell(NETWORK_GUARD_SOURCE)
    guard.metadata["tags"] = ["injected-network-guard"]
    notebook.cells.insert(0, guard)


def _inject_fast_smoke_override(notebook) -> None:
    """Insert ``FAST_SMOKE = True`` after the single parameters-tagged cell."""

    import nbformat

    tagged_indices = [
        index
        for index, cell in enumerate(notebook.cells)
        if cell.cell_type == "code"
        and PARAMETERS_TAG in cell.get("metadata", {}).get("tags", [])
    ]
    if len(tagged_indices) != 1:
        raise SystemExit(
            f"--fast-smoke requires exactly one code cell tagged "
            f"{PARAMETERS_TAG!r}; found {len(tagged_indices)}"
        )
    override = nbformat.v4.new_code_cell(FAST_SMOKE_OVERRIDE_SOURCE)
    override.metadata["tags"] = ["injected-parameters"]
    notebook.cells.insert(tagged_indices[0] + 1, override)


def _execute_in_process(
    notebook_path: Path,
    *,
    cell_timeout_s: int,
    fast_smoke: bool,
) -> None:
    """Runner-subprocess mode: execute one notebook on a throwaway copy."""

    import nbformat
    from nbclient import NotebookClient

    if not notebook_path.is_file():
        raise SystemExit(f"notebook not found: {notebook_path}")

    with tempfile.TemporaryDirectory(prefix="nb-smoke-") as working_dir:
        scratch = Path(working_dir) / notebook_path.name
        shutil.copyfile(notebook_path, scratch)
        notebook = nbformat.read(scratch, as_version=4)
        if fast_smoke:
            _inject_fast_smoke_override(notebook)
        # Injected last so it is cell 0 and active before any real cell runs.
        _inject_network_guard(notebook)
        client = NotebookClient(
            notebook,
            timeout=cell_timeout_s,
            kernel_name="python3",
            resources={"metadata": {"path": str(scratch.parent)}},
        )
        # nbclient has no ``env`` trait: the mapping must travel through
        # execute() into KernelManager.start_kernel to reach the kernel.
        client.execute(env=_kernel_environment())


def _namespace_prefix_candidates() -> Iterator[list[str]]:
    """The prefixes worth probing here, least privileged first.

    The normal path enters a child user namespace, mapping the invoking user
    to namespace root. This permits loopback setup without retaining any
    capability over the host network namespace.

    Ubuntu's AppArmor policy can deny that path. The passwordless-sudo fallback
    therefore creates and initializes a network namespace as root, then uses
    setpriv to return to the invoking UID/GID, clear supplementary groups and
    every capability set, and prohibit new privileges before running any
    notebook code. A bare privileged network namespace would be escapable;
    dropping capabilities and disabling setuid/file-capability escalation is
    essential. Both paths are tested for a refused host-namespace entry.

    Do not use ``sudo unshare --user --map-root-user`` here: it maps outer root,
    not the invoking user, so private checkout and temporary paths become
    inaccessible. The fallback keeps the caller's actual filesystem identity.
    Candidates are lazy so a working unprivileged path never asks for sudo.
    """

    unshare = shutil.which("unshare")
    # nsenter is required, not optional: it is how the probe below observes that
    # the namespace it just made cannot be left again.  Without it the only
    # thing standing behind the offline contract would be the argument that
    # these forms confine, and this module's whole discipline is that an
    # argument is not evidence.  util-linux ships unshare and nsenter together,
    # so demanding both costs nothing an environment that has one would notice.
    if unshare is None or shutil.which("ip") is None or shutil.which("nsenter") is None:
        return
    yield [
        unshare,
        "--user",
        "--map-root-user",
        "--net",
        "--",
        "sh",
        "-c",
        _NAMESPACE_SHELL,
    ]
    sudo = shutil.which("sudo")
    setpriv = shutil.which("setpriv")
    if sudo is None or setpriv is None:
        return
    # ``-n`` never prompts.  A sudo that would ask for a password is the same
    # answer as no sudo at all here, because nothing is watching a CI step to
    # type one, and offering the form regardless would spend a probe proving it.
    try:
        elevation = subprocess.run(
            [sudo, "-n", "true"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return
    if elevation.returncode != 0:
        return
    yield [
        sudo,
        "-n",
        unshare,
        "--net",
        "--",
        "sh",
        "-c",
        _NAMESPACE_SHELL,
        setpriv,
        f"--reuid={os.geteuid()}",
        f"--regid={os.getegid()}",
        "--clear-groups",
        "--bounding-set=-all",
        "--inh-caps=-all",
        "--ambient-caps=-all",
        "--no-new-privs",
        "--",
    ]


def _sudo_escalation(isolation_prefix: list[str]) -> list[str]:
    """The ``sudo`` invocation that reaches processes started by ``prefix``.

    Empty for every unelevated prefix, because there is nothing to escalate
    through and pretending otherwise would hide a failure the caller must see.
    """

    if (
        len(isolation_prefix) >= 2
        and isolation_prefix[1] == "-n"
        and Path(isolation_prefix[0]).name == "sudo"
    ):
        return [isolation_prefix[0], "-n"]
    return []


def _network_namespace_prefix() -> list[str] | None:
    """A command prefix that runs its argument in a loopback-only namespace.

    Returns ``None`` when this environment cannot provide one.  Availability is
    established by *doing* it rather than by inspecting the platform: unshare
    and ip must exist, the namespace must actually be created, and it must
    contain loopback and nothing else.  A probe that merely started is not
    evidence, so the interface list is read back and checked — an unexpected
    result means the prefix is not returned rather than silently used.  That
    check is what makes an ``unshare`` which silently did not take, or a sudo
    rule that ran the command outside a namespace, a refusal instead of a lane
    reporting an offline contract with a route to the outside still in place.

    The forms probed, and why they are ordered as they are, are documented on
    :func:`_namespace_prefix_candidates`.
    """

    if sys.platform != "linux":
        return None
    outer_net_namespace = f"/proc/{os.getpid()}/ns/net"
    # The probe must also be usable by the caller: namespace root mapped to
    # outer root can list interfaces but cannot traverse a caller-owned 0700
    # directory. A private canary catches that before choosing a prefix.
    with tempfile.TemporaryDirectory(prefix="nb-namespace-probe-") as probe_dir:
        canary = Path(probe_dir) / "caller-owned"
        canary.touch(mode=0o600)
        return _probe_namespace_candidates(outer_net_namespace, canary)


def _probe_namespace_candidates(
    outer_net_namespace: str, canary: Path
) -> list[str] | None:
    for prefix in _namespace_prefix_candidates():
        try:
            probe = subprocess.run(
                [
                    *prefix,
                    "sh",
                    "-c",
                    _NAMESPACE_PROBE,
                    "sh",
                    outer_net_namespace,
                    str(canary),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if probe.returncode != 0:
            continue
        interfaces = {
            line.split(":", 2)[1].strip().split("@", 1)[0]
            for line in probe.stdout.splitlines()
            if line.count(":") >= 2
        }
        # Both questions must be answered, and answered affirmatively. Where the
        # process starts is the interface list; whether it can leave is the
        # escape attempt. A prefix that passes the first and fails the second is
        # precisely the privileged form this function used to return: loopback
        # only, and one setns away from the host network.
        if interfaces != {"lo"}:
            continue
        if "ESCAPE_REFUSED" not in probe.stdout:
            continue
        if _sudo_escalation(prefix):
            status = dict(
                line.split(":", 1) for line in probe.stdout.splitlines() if ":" in line
            )
            # Observe the final credentials, not just the setpriv arguments.
            # no_new_privs prevents regaining host capabilities through sudo,
            # setuid executables, or file capabilities after this probe.
            if any(
                status.get(field, "").split() != [str(identity)] * 4
                for field, identity in (("Uid", os.geteuid()), ("Gid", os.getegid()))
            ):
                continue
            if status.get("NoNewPrivs", "").strip() != "1":
                continue
            if "Groups" not in status or status["Groups"].strip():
                continue
            if any(
                status.get(field, "").strip() != "0000000000000000"
                for field in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")
            ):
                continue
        return prefix
    return None


def _resolve_network_isolation(mode: str) -> list[str]:
    """Return the command prefix demanded by ``mode``, or refuse.

    ``required`` is the default because the alternative is a lane that reports
    an offline contract it did not enforce.  The in-kernel guard cannot stand in
    for the namespace: a subprocess, a C extension, or a direct ``_socket`` call
    walks straight past it.
    """

    if mode == "off":
        return []
    prefix = _network_namespace_prefix()
    if prefix is not None:
        return prefix
    if mode == "required":
        raise SystemExit(
            "Network isolation is unavailable on this platform, so the "
            "notebooks cannot be executed under the offline contract: the "
            "in-kernel guard is a tripwire, not a sandbox, and a subprocess or "
            "a direct _socket call reaches the network past it. Linux with "
            "unshare(1) and ip(8) provides it, through unprivileged user "
            "namespaces, an existing CAP_SYS_ADMIN, or passwordless sudo; on "
            "Ubuntu 24.04 and later the first of those needs "
            "kernel.apparmor_restrict_unprivileged_userns=0. Pass "
            "--network-isolation auto to run anyway with the tripwire alone, "
            "knowing the contract is not enforced."
        )
    print(
        "WARNING: no network namespace available; notebooks run with the "
        "in-kernel guard only, which a subprocess or a direct _socket call "
        "bypasses. The offline contract is NOT enforced in this run."
    )
    return []


def _runner_command(
    notebook_path: Path,
    *,
    cell_timeout_s: int,
    fast_smoke: bool,
    isolation_prefix: list[str],
) -> list[str]:
    """The full argv for one runner subprocess, isolation included."""

    runner = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--single",
        str(notebook_path),
        "--cell-timeout",
        str(cell_timeout_s),
    ]
    if fast_smoke:
        runner.append("--fast-smoke")
    if not isolation_prefix:
        return runner
    # sudo resets the environment it hands on (env_reset is the sudoers
    # default), so the MPLBACKEND this process set for the kernel would be
    # dropped on the way through and a notebook could reach for an interactive
    # backend on a headless runner.  Re-stating it inside the namespace costs
    # one exec and keeps every isolation form running the same kernel
    # environment. Restore the caller's home as well, so Jupyter and plotting
    # libraries use its writable configuration/cache directories after sudo.
    inner = (
        ["env", f"HOME={Path.home()}", "MPLBACKEND=Agg", *runner]
        if _sudo_escalation(isolation_prefix)
        else runner
    )
    return [*isolation_prefix, *inner]


def _kill_process_group(process: subprocess.Popen, escalation: list[str]) -> None:
    """Kill the runner and its kernel; both live in one session/group.

    ``escalation`` is :func:`_sudo_escalation` for the isolation prefix that
    started the process, and is empty for every unelevated one.  It exists
    because kill(2) delivers a signal only when the sender's real or effective
    uid matches the target's real or saved uid: everything behind sudo has both
    set to root, so an unprivileged parent's killpg raises EPERM.  Left
    unhandled the budget would surface a PermissionError instead of its own
    message while the notebook it was meant to bound kept running.

    Reissuing through the same interpreter rather than kill(1) keeps the
    semantics identical to the call that just failed — one signal to one process
    group, no shell, no dependency on procps being installed.  With nothing to
    escalate through, EPERM is raised rather than swallowed: a budget that
    silently failed to kill is a budget that was never enforced.
    """

    if os.name == "posix":
        # Enumerated before anything is signalled, and this order is the whole
        # point: the kernel is a grandchild in a session of its own, so the
        # moment the runner dies the kernel is reparented to init and nothing
        # connects it to this run any more. The one instant it can be found is
        # while its parent is still alive.
        strays = _descendant_pids(process.pid)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            # Nothing to escalate through means the budget could not be
            # enforced, and a budget that silently failed to kill was never a
            # budget. Surface it rather than returning as though it worked.
            if not escalation:
                raise
        for stray in strays:
            # A pid can in principle be recycled between the snapshot above and
            # this signal. The window is the time taken by one killpg, and the
            # alternative — leaving the kernel running — is the failure this
            # exists to prevent, so the exposure is accepted rather than hidden.
            try:
                os.kill(stray, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError:
                if not escalation:
                    raise
        if escalation:
            # Unconditional, not a fallback for EPERM. kill(2) reports success
            # when the signal reached *at least one* member of the group, and
            # under sudo the group holds both the signalable sudo process and
            # the root descendants it started. Killing sudo alone therefore
            # returns success while the kernel — the thing the budget exists to
            # stop — keeps running with the notebook still executing in it. The
            # privileged pass is the only one that can reach those descendants,
            # so it runs whenever the group was started privileged, whatever the
            # unprivileged attempt reported.
            subprocess.run(
                [
                    *escalation,
                    sys.executable,
                    "-c",
                    _REISSUE_KILLPG,
                    str(process.pid),
                    *(str(stray) for stray in strays),
                ],
                check=False,
            )
    else:
        process.kill()
    process.wait()


def _run_with_budget(
    notebook_path: Path,
    *,
    cell_timeout_s: int,
    budget_s: int,
    fast_smoke: bool,
    isolation_prefix: list[str] | None = None,
) -> float:
    """Execute one notebook in a subprocess killed at the wall-clock budget."""

    prefix = [] if isolation_prefix is None else isolation_prefix
    command = _runner_command(
        notebook_path,
        cell_timeout_s=cell_timeout_s,
        fast_smoke=fast_smoke,
        isolation_prefix=prefix,
    )
    start = time.perf_counter()
    process = subprocess.Popen(
        command,
        env=_kernel_environment(),
        start_new_session=True,
    )
    try:
        returncode = process.wait(timeout=budget_s)
    except subprocess.TimeoutExpired:
        _kill_process_group(process, _sudo_escalation(prefix))
        raise SystemExit(
            f"{notebook_path.name} exceeded the whole-notebook budget: "
            f"killed after {budget_s}s"
        ) from None
    if returncode != 0:
        raise SystemExit(
            f"notebook runner subprocess exited with code {returncode}"
        )
    return time.perf_counter() - start


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("notebooks", nargs="*", type=Path)
    parser.add_argument(
        "--class",
        dest="execution_class",
        help="Execute every manifest canonical notebook with this execution class.",
    )
    parser.add_argument(
        "--fast-smoke",
        action="store_true",
        help=(
            "Inject FAST_SMOKE = True after each notebook's parameters cell "
            "so slow studies run their representative fast parameterization."
        ),
    )
    parser.add_argument(
        "--single",
        action="store_true",
        help=(
            "Internal runner mode: execute exactly one notebook in-process "
            "without budget enforcement, and without isolating the network "
            "again — the parent enforces both, and this process is already "
            "inside the namespace it created."
        ),
    )
    parser.add_argument("--cell-timeout", type=int, default=DEFAULT_CELL_TIMEOUT_S)
    parser.add_argument("--notebook-budget", type=int, default=DEFAULT_NOTEBOOK_BUDGET_S)
    parser.add_argument(
        "--network-isolation",
        choices=NETWORK_ISOLATION_MODES,
        default=DEFAULT_NETWORK_ISOLATION,
        help=(
            "'required' (default) refuses to run where the kernel cannot be "
            "placed in a loopback-only network namespace; 'auto' falls back to "
            "the in-kernel guard alone and says so; 'off' never isolates."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.single:
        if args.execution_class or len(args.notebooks) != 1:
            parser.error("--single executes exactly one explicit notebook path.")
        notebook_path = args.notebooks[0]
        resolved = notebook_path if notebook_path.is_absolute() else ROOT / notebook_path
        _execute_in_process(
            resolved,
            cell_timeout_s=args.cell_timeout,
            fast_smoke=args.fast_smoke,
        )
        return 0

    selected: list[Path] = list(args.notebooks)
    if args.execution_class:
        selected.extend(_canonical_paths_for_class(args.execution_class))
    if not selected:
        parser.error("provide notebook paths or --class to select from the manifest.")

    # Resolved once: the probe starts a process, and the answer cannot change
    # between notebooks in one run.
    isolation_prefix = _resolve_network_isolation(args.network_isolation)
    failures = 0
    for notebook_path in selected:
        resolved = notebook_path if notebook_path.is_absolute() else ROOT / notebook_path
        try:
            elapsed = _run_with_budget(
                resolved,
                cell_timeout_s=args.cell_timeout,
                budget_s=args.notebook_budget,
                fast_smoke=args.fast_smoke,
                isolation_prefix=isolation_prefix,
            )
        except SystemExit as exit_error:
            print(f"FAIL {notebook_path}: {exit_error}")
            failures += 1
        except Exception as error:  # noqa: BLE001 - report and continue
            print(f"FAIL {notebook_path}: {type(error).__name__}: {error}")
            failures += 1
        else:
            print(f"ok   {notebook_path}  ({elapsed:.1f}s)")

    if failures:
        print(f"{failures} notebook(s) failed the smoke contract.")
        return 1
    print(f"{len(selected)} notebook(s) executed cleanly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
