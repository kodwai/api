from __future__ import annotations

import json

import pytest

from app.operator_scoring.itembank import (
    InMemoryItemRepository,
    Item,
    ItemValidationError,
    JsonItemRepository,
    item_from_dict,
    item_to_dict,
)

# --- Item validation ---------------------------------------------------------

def test_minimal_item_is_valid():
    item = Item(id="c1", a=1.8, b=0.80)
    assert item.id == "c1"
    assert item.a == 1.8
    assert item.b == 0.80
    assert item.s is None
    assert item.has_baseline_stats is False


def test_item_rejects_nonpositive_a():
    with pytest.raises(ItemValidationError):
        Item(id="c1", a=0.0, b=0.0)
    with pytest.raises(ItemValidationError):
        Item(id="c1", a=-1.0, b=0.0)


def test_item_rejects_nonpositive_s_when_set():
    with pytest.raises(ItemValidationError):
        Item(id="c1", a=1.0, b=0.0, s=0.0)
    with pytest.raises(ItemValidationError):
        Item(id="c1", a=1.0, b=0.0, s=-0.1)
    # None is allowed (Layer E may derive it later).
    assert Item(id="c1", a=1.0, b=0.0, s=None).s is None


def test_item_rejects_ceiling_equal_mu0():
    with pytest.raises(ItemValidationError):
        Item(
            id="c1",
            a=1.0,
            b=0.0,
            mu0=0.55,
            sigma0=0.08,
            M=20,
            ceiling=0.55,
        )


def test_item_accepts_full_baseline():
    item = Item(
        id="ledger",
        a=1.8,
        b=0.80,
        s=0.10869249724298408,
        mu0=0.55,
        sigma0=0.08,
        M=20,
        ceiling=0.97,
        sigma_intrinsic=0.10,
    )
    assert item.has_baseline_stats is True


def test_has_baseline_stats_requires_all_four():
    # Missing M -> not a full baseline.
    item = Item(id="c1", a=1.0, b=0.0, mu0=0.55, sigma0=0.08, ceiling=0.97)
    assert item.has_baseline_stats is False


# --- InMemoryItemRepository: upsert / get / list -----------------------------

def test_in_memory_upsert_get_list():
    repo = InMemoryItemRepository()
    assert repo.get("missing") is None
    assert repo.list() == []

    a_item = Item(id="a", a=1.0, b=0.1)
    b_item = Item(id="b", a=2.0, b=0.5)
    repo.upsert(a_item)
    repo.upsert(b_item)

    assert repo.get("a") is a_item
    assert repo.get("b") is b_item
    ids = {i.id for i in repo.list()}
    assert ids == {"a", "b"}


def test_in_memory_upsert_replaces_existing():
    repo = InMemoryItemRepository()
    repo.upsert(Item(id="a", a=1.0, b=0.1))
    repo.upsert(Item(id="a", a=2.0, b=0.9))
    got = repo.get("a")
    assert got is not None
    assert got.a == 2.0
    assert got.b == 0.9
    assert len(repo.list()) == 1


def test_in_memory_seed_from_iterable():
    repo = InMemoryItemRepository([Item(id="a", a=1.0, b=0.1), Item(id="b", a=1.0, b=0.2)])
    assert {i.id for i in repo.list()} == {"a", "b"}


# --- item_to_dict / item_from_dict round-trip --------------------------------

def test_json_round_trip_preserves_a_vec_tuple():
    item = Item(
        id="md",
        a=1.5,
        b=0.6,
        s=0.11,
        a_vec=(1.5, 0.0, 0.0, 0.0, 0.0),
        dims=("dec", "ver", "rec", "taste", "eff"),
        name="Search index",
        category="backend",
        difficulty="hard",
    )
    # to_dict -> JSON text -> back, exactly as a persistence layer would.
    reloaded = item_from_dict(json.loads(json.dumps(item_to_dict(item))))

    assert reloaded == item
    assert isinstance(reloaded.a_vec, tuple)
    assert reloaded.a_vec == (1.5, 0.0, 0.0, 0.0, 0.0)
    assert isinstance(reloaded.dims, tuple)
    assert reloaded.dims == ("dec", "ver", "rec", "taste", "eff")


def test_item_from_dict_ignores_unknown_keys():
    d = item_to_dict(Item(id="c1", a=1.0, b=0.0))
    d["totally_unknown"] = 999
    item = item_from_dict(d)
    assert item.id == "c1"
    assert not hasattr(item, "totally_unknown")


def test_item_to_dict_covers_all_fields():
    d = item_to_dict(Item(id="c1", a=1.0, b=0.0))
    assert d["id"] == "c1"
    assert d["a"] == 1.0
    assert d["s"] is None
    assert d["a_vec"] is None


# --- JsonItemRepository: persistence across two instances --------------------

def test_json_repo_persists_across_instances(tmp_path):
    path = str(tmp_path / "items.json")

    first = JsonItemRepository(path, autosave=True)
    ledger = Item(
        id="ledger",
        a=1.8,
        b=0.80,
        s=0.10869249724298408,
        mu0=0.55,
        sigma0=0.08,
        M=20,
        ceiling=0.97,
        sigma_intrinsic=0.10,
        a_vec=(1.8, 0.0, 0.0, 0.0, 0.0),
        name="Ledger",
    )
    first.upsert(ledger)
    first.upsert(Item(id="rate_limiter_trap", a=2.0, b=0.50, s=0.10))

    # A brand-new instance on the same path must see the persisted items.
    second = JsonItemRepository(path, autosave=True)
    assert {i.id for i in second.list()} == {"ledger", "rate_limiter_trap"}

    got = second.get("ledger")
    assert got is not None
    assert got == ledger
    assert isinstance(got.a_vec, tuple)
    assert got.a_vec == (1.8, 0.0, 0.0, 0.0, 0.0)
    assert got.has_baseline_stats is True


def test_json_repo_missing_file_starts_empty(tmp_path):
    path = str(tmp_path / "does_not_exist.json")
    repo = JsonItemRepository(path)
    assert repo.list() == []
    assert repo.get("x") is None


def test_json_repo_no_autosave_requires_manual_save(tmp_path):
    path = str(tmp_path / "items.json")
    repo = JsonItemRepository(path, autosave=False)
    repo.upsert(Item(id="a", a=1.0, b=0.1))

    # Nothing flushed yet -> a fresh instance sees nothing.
    assert JsonItemRepository(path).list() == []

    repo.save()
    assert {i.id for i in JsonItemRepository(path).list()} == {"a"}
