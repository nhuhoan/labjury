import pytest

from labjury.decisions import ChoiceQuestion, NoulQuestion
from labjury.plugins import RubricStore
from labjury.rubrics import InMemoryRubricStore, Rubric
from labjury.testing import assert_rubric_store_contract


def _q(prompt="graphic violence?"):
    return NoulQuestion("violence", prompt)


async def test_register_then_resolve():
    store = InMemoryRubricStore()
    r = await store.register("violence", _q(), "v1")
    assert r == Rubric("violence", _q(), "v1")
    assert await store.resolve("violence") == r


async def test_resolve_returns_latest_version():
    store = InMemoryRubricStore()
    await store.register("violence", _q("old"), "v1")
    await store.register("violence", _q("new"), "v2")
    assert (await store.resolve("violence")).version == "v2"


async def test_get_old_version_survives_supersession():
    store = InMemoryRubricStore()
    await store.register("violence", _q("old"), "v1")
    await store.register("violence", _q("new"), "v2")
    assert (await store.get("violence", "v1")).question == _q("old")


async def test_history_in_registration_order():
    store = InMemoryRubricStore()
    await store.register("violence", _q(), "v1")
    await store.register("violence", _q("x"), "v2")
    assert await store.history("violence") == ["v1", "v2"]


async def test_version_is_immutable_once_published():
    store = InMemoryRubricStore()
    await store.register("violence", _q("first"), "v1")
    with pytest.raises(ValueError):
        await store.register("violence", _q("changed"), "v1")


async def test_reregister_same_version_same_question_is_idempotent():
    store = InMemoryRubricStore()
    await store.register("violence", _q(), "v1")
    r = await store.register("violence", _q(), "v1")
    assert r.version == "v1"
    assert await store.history("violence") == ["v1"]


async def test_unregistered_label_is_empty():
    store = InMemoryRubricStore()
    assert await store.resolve("nope") is None
    assert await store.get("nope", "v1") is None
    assert await store.history("nope") == []


def test_in_memory_store_is_a_rubric_store():
    assert isinstance(InMemoryRubricStore(), RubricStore)


async def test_conformance_suite_passes_for_in_memory():
    await assert_rubric_store_contract(InMemoryRubricStore)


async def test_published_rubric_cannot_change_through_input_or_returned_question():
    store = InMemoryRubricStore()
    question = ChoiceQuestion("q", "original?", ["yes", "no"])
    published = await store.register("label", question, "v1")
    question.prompt = "changed input?"
    question.options.append("maybe")
    published.question.prompt = "changed result?"
    resolved = await store.resolve("label")
    resolved.question.options.append("other")
    historical = await store.get("label", "v1")
    assert historical.question == ChoiceQuestion("q", "original?", ["yes", "no"])
    with pytest.raises(ValueError):
        await store.register("label", question, "v1")
