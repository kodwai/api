"""Item bank for the operator scoring core.

An :class:`Item` carries everything the numeric layers need to score a
challenge: the IRT calibration ``(a, b, s)`` (Layer D), the Layer-E baseline
stats ``(mu0, sigma0, M, ceiling, sigma_intrinsic)``, an optional
multidimensional discrimination vector ``a_vec``, and light presentation
metadata. Items are stored behind the :class:`ItemRepository` Protocol; two
concrete stores ship here, an in-memory dict and a JSON-file store with
autosave. ``item_to_dict``/``item_from_dict`` are the round-trip bridge, and
``item_from_dict`` normalizes JSON arrays back into the tuples the dataclass
expects.

Framework-free: stdlib only (``dataclasses`` + ``json`` + ``pathlib``), no
pydantic/fastapi/libsql. Validation lives in ``Item.__post_init__`` and raises
the typed :class:`ItemValidationError`, never a bare assert.
"""
from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class ItemValidationError(ValueError):
    """Raised by :meth:`Item.__post_init__` on an ill-posed item."""


# Tuple-typed fields whose JSON-array form must be coerced back to a tuple.
_TUPLE_FIELDS = ("a_vec", "dims")


@dataclass
class Item:
    """One calibrated challenge in the item bank.

    ``id`` doubles as the ``challenge_id`` in the live scoring path. ``a``/``b``
    are the scalar IRT discrimination/difficulty and are always required; ``s``
    (observation noise) may be omitted and later derived by Layer E. The
    ``mu0``/``sigma0``/``M``/``ceiling``/``sigma_intrinsic`` block is the
    Layer-E baseline; when a full baseline is present the ceiling must differ
    from ``mu0`` so ``denom = ceiling - mu0`` stays non-degenerate.
    """

    id: str
    a: float
    b: float
    s: float | None = None
    mu0: float | None = None
    sigma0: float | None = None
    M: int | None = None
    ceiling: float | None = None
    sigma_intrinsic: float | None = None
    a_vec: tuple[float, ...] | None = None
    name: str = ""
    category: str | None = None
    difficulty: str | None = None
    dims: tuple[str, ...] | None = None
    ai_baseline: float | None = None

    def __post_init__(self) -> None:
        if self.a <= 0:
            raise ItemValidationError(f"Item.a must be > 0 (got {self.a!r})")
        if self.s is not None and self.s <= 0:
            raise ItemValidationError(f"Item.s must be > 0 when set (got {self.s!r})")
        # A ceiling equal to the baseline mean collapses denom = ceiling - mu0
        # to zero, which would blow up Layer E; reject it whenever both are set.
        if (
            self.ceiling is not None
            and self.mu0 is not None
            and self.ceiling == self.mu0
        ):
            raise ItemValidationError(
                f"Item.ceiling must differ from Item.mu0 (both {self.ceiling!r})"
            )

    @property
    def has_baseline_stats(self) -> bool:
        """True when the item carries a full Layer-E baseline of its own."""
        return (
            self.mu0 is not None
            and self.sigma0 is not None
            and self.M is not None
            and self.ceiling is not None
        )


class ItemRepository(Protocol):
    """Structural contract every item store implements."""

    def get(self, item_id: str) -> Item | None: ...
    def list(self) -> list[Item]: ...
    def upsert(self, item: Item) -> None: ...


class InMemoryItemRepository:
    """Dict-backed item store; nothing is persisted across processes."""

    def __init__(self, items: Iterable[Item] | None = None) -> None:
        self._items: dict[str, Item] = {}
        if items is not None:
            for item in items:
                self._items[item.id] = item

    def get(self, item_id: str) -> Item | None:
        return self._items.get(item_id)

    def list(self) -> list[Item]:
        return list(self._items.values())

    def upsert(self, item: Item) -> None:
        self._items[item.id] = item


class JsonItemRepository:
    """Item store backed by a JSON file on ``path``.

    On construction the file (if present) is loaded into memory. When
    ``autosave`` is true every :meth:`upsert` rewrites the file, so a second
    ``JsonItemRepository`` pointed at the same path sees the persisted items.
    Call :meth:`save` explicitly to flush when ``autosave`` is false.
    """

    def __init__(self, path: str, autosave: bool = True) -> None:
        self._path = path
        self._autosave = autosave
        self._items: dict[str, Item] = {}
        self._load()

    def _load(self) -> None:
        # Guarded like JsonCalibrationRepository: a missing/corrupt file yields an
        # empty store rather than raising, and one invalid record is skipped so it
        # cannot discard every valid item alongside it.
        path = Path(self._path)
        if not path.exists():
            return
        try:
            raw = path.read_text(encoding="utf-8")
            if not raw.strip():
                return
            data = json.loads(raw)
        except (OSError, ValueError):
            return
        if not isinstance(data, list):
            return
        for entry in data:
            if not isinstance(entry, dict):
                continue
            try:
                item = item_from_dict(entry)
            except (ValueError, TypeError):
                continue
            self._items[item.id] = item

    def get(self, item_id: str) -> Item | None:
        return self._items.get(item_id)

    def list(self) -> list[Item]:
        return list(self._items.values())

    def upsert(self, item: Item) -> None:
        self._items[item.id] = item
        if self._autosave:
            self.save()

    def save(self) -> None:
        payload = [item_to_dict(item) for item in self._items.values()]
        Path(self._path).write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )


def item_to_dict(item: Item) -> dict[str, Any]:
    """Serialize an item to a plain, JSON-ready dict (tuples become arrays)."""
    return dataclasses.asdict(item)


def item_from_dict(d: dict[str, Any]) -> Item:
    """Build an :class:`Item` from a dict, ignoring unknown keys.

    JSON arrays destined for the tuple-typed fields (``a_vec``, ``dims``) are
    coerced back into tuples so a value survives a JSON round trip unchanged.
    """
    known = {f.name for f in dataclasses.fields(Item)}
    kwargs: dict[str, Any] = {}
    for key, value in d.items():
        if key not in known:
            continue
        if key in _TUPLE_FIELDS and isinstance(value, list):
            value = tuple(value)
        kwargs[key] = value
    return Item(**kwargs)
