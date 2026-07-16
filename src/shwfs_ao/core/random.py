"""Stable named NumPy random streams derived from one immutable root seed.

Stream derivation uses canonical JSON and SHA-256, then initializes NumPy's
explicit PCG64 bit generator from the full digest.  The public scheme ID and
frozen tests make any future derivation change an intentional schema change.
"""

from __future__ import annotations

from collections.abc import Iterable
import hashlib
import json
from typing import Final

import numpy as np


DERIVATION_SCHEME_ID: Final = "shwfs_ao.random.sha256-json-pcg64-v1"

DEFAULT_RANDOM_DOMAINS: tuple[str, ...] = (
    "detector.realization",
    "detector.shot_noise",
    "detector.read_noise",
    "calibration",
    "atmosphere",
    "ncpa",
)

_Key = tuple[str | int, ...]
_ScopeFrame = tuple[str, _Key]


class RandomStreamError(ValueError):
    """Raised when a random-stream registration or request is invalid."""


class NamedRandomStreams:
    """Provide persistent, keyed, and scoped generators for named domains.

    Args:
        root_seed: Immutable non-negative integer from which every stream is
            derived independently.
        domains: Explicit top-level registry.  It must contain all required
            default domains; extra application domains are allowed.

    Domain derivation never depends on registration order or Python's
    randomized ``hash()``.  A persistent generator is cached per domain.
    Keyed generators and scoped views use separate deterministic children and
    cannot advance those runtime generators.
    """

    def __init__(
        self,
        root_seed: int,
        *,
        domains: Iterable[str] = DEFAULT_RANDOM_DOMAINS,
    ) -> None:
        self._root_seed = _validate_root_seed(root_seed)
        self._domains = _validated_registry(domains)
        missing = tuple(
            domain for domain in DEFAULT_RANDOM_DOMAINS if domain not in self._domains
        )
        if missing:
            raise RandomStreamError(
                "Random-stream registry is missing required domains: "
                f"{list(missing)}."
            )
        self._scope_path: tuple[_ScopeFrame, ...] = ()
        self._persistent_generators: dict[
            tuple[tuple[_ScopeFrame, ...], str], np.random.Generator
        ] = {}

    @property
    def root_seed(self) -> int:
        """Return the immutable root seed."""

        return self._root_seed

    @property
    def derivation_scheme_id(self) -> str:
        """Return the versioned derivation algorithm identifier."""

        return DERIVATION_SCHEME_ID

    @property
    def registered_domains(self) -> tuple[str, ...]:
        """Return the top-level registry in explicit registration order."""

        return tuple(self._domains)

    def register_domain(self, domain: str) -> None:
        """Register one additional top-level domain without perturbing others."""

        if self._scope_path:
            raise RandomStreamError(
                "Random-stream domains can only be registered on a top-level provider."
            )
        name = _validate_name(domain, label="domain")
        if name in self._domains:
            raise RandomStreamError(f"Duplicate random-stream domain: {name!r}.")
        self._domains[name] = None

    def reset(self) -> None:
        """Discard root and retained-view generators for an exact replay."""

        self._persistent_generators.clear()

    def generator(self, domain: str) -> np.random.Generator:
        """Return the persistent generator for an explicitly registered domain."""

        name = self._require_registered(domain)
        cache_key = (self._scope_path, name)
        generator = self._persistent_generators.get(cache_key)
        if generator is None:
            generator = self._new_generator(name, ())
            self._persistent_generators[cache_key] = generator
        return generator

    def keyed_generator(
        self,
        domain: str,
        *,
        key: _Key,
    ) -> np.random.Generator:
        """Return a fresh replayable generator without advancing persistent state."""

        name = self._require_registered(domain)
        stable_key = _validate_key(key)
        return self._new_generator(name, stable_key)

    def stream_id(
        self,
        domain: str,
        *,
        key: _Key = (),
    ) -> str:
        """Return the stable identifier for a domain/scope/key derivation."""

        name = self._require_registered(domain)
        stable_key = _validate_key(key)
        digest = self._derivation_digest(name, stable_key)
        return f"{DERIVATION_SCHEME_ID}:{digest.hex()}"

    def scoped(
        self,
        scope: str,
        *,
        key: _Key = (),
    ) -> NamedRandomStreams:
        """Return an isolated view that derives all requests beneath a scope."""

        frame = (_validate_name(scope, label="scope"), _validate_key(key))
        view = object.__new__(type(self))
        view._root_seed = self._root_seed
        view._domains = self._domains
        view._scope_path = (*self._scope_path, frame)
        view._persistent_generators = self._persistent_generators
        return view

    def _require_registered(self, domain: str) -> str:
        name = _validate_name(domain, label="domain")
        if name not in self._domains:
            raise RandomStreamError(
                f"Unknown random-stream domain {name!r}; register it explicitly."
            )
        return name

    def _new_generator(self, domain: str, key: _Key) -> np.random.Generator:
        seed = int.from_bytes(self._derivation_digest(domain, key), "big")
        return np.random.Generator(np.random.PCG64(seed))

    def _derivation_digest(self, domain: str, key: _Key) -> bytes:
        record = {
            "domain": domain,
            "key": _encoded_key(key),
            "root_seed": str(self._root_seed),
            "scheme_id": DERIVATION_SCHEME_ID,
            "scopes": [
                {"key": _encoded_key(scope_key), "scope": scope}
                for scope, scope_key in self._scope_path
            ],
        }
        payload = json.dumps(
            record,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).digest()


def _legacy_sequential_child_seeds(
    root_seed: int | None,
    count: int,
) -> tuple[int, ...]:
    """Replay the pre-refactor ordered ``default_rng`` child-seed sequence.

    This helper exists only for installed legacy adapters.  Canonical runtime
    code uses named, keyed streams; the adapters need the historical
    order-dependent sequence so frozen seeded simulations remain unchanged
    while the physical measurement loop lives in the canonical WFS layer.
    """

    if root_seed is not None and (type(root_seed) is not int or root_seed < 0):
        raise RandomStreamError(
            "root_seed must be a non-negative integer or None; "
            f"got {root_seed!r}."
        )
    if type(count) is not int or count < 0:
        raise RandomStreamError(
            f"count must be a non-negative integer; got {count!r}."
        )
    generator = np.random.default_rng(root_seed)
    return tuple(
        int(generator.integers(0, 2**31 - 1))
        for _ in range(count)
    )


def _validate_root_seed(root_seed: object) -> int:
    if type(root_seed) is not int or root_seed < 0:
        raise RandomStreamError(
            f"root_seed must be a non-negative integer; got {root_seed!r}."
        )
    return root_seed


def _validated_registry(domains: Iterable[str]) -> dict[str, None]:
    if isinstance(domains, (str, bytes)):
        raise RandomStreamError("domains must be an iterable of domain strings.")
    try:
        candidates = tuple(domains)
    except TypeError as exc:
        raise RandomStreamError(
            "domains must be an iterable of domain strings."
        ) from exc

    registry: dict[str, None] = {}
    for domain in candidates:
        name = _validate_name(domain, label="domain")
        if name in registry:
            raise RandomStreamError(f"Duplicate random-stream domain: {name!r}.")
        registry[name] = None
    return registry


def _validate_name(value: object, *, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise RandomStreamError(
            f"{label} must be a non-empty string without surrounding whitespace; "
            f"got {value!r}."
        )
    return value


def _validate_key(key: object) -> _Key:
    if not isinstance(key, tuple):
        raise RandomStreamError(
            f"key must be a tuple of strings or integers; got {key!r}."
        )
    for index, item in enumerate(key):
        if isinstance(item, bool) or not isinstance(item, (str, int)):
            raise RandomStreamError(
                f"key[{index}] must be a string or integer; got {item!r}."
            )
    return key


def _encoded_key(key: _Key) -> list[dict[str, str]]:
    return [
        {
            "kind": "int" if isinstance(item, int) else "str",
            "value": str(item) if isinstance(item, int) else item,
        }
        for item in key
    ]


__all__ = (
    "DEFAULT_RANDOM_DOMAINS",
    "DERIVATION_SCHEME_ID",
    "NamedRandomStreams",
    "RandomStreamError",
)
