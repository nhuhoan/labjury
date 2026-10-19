import pytest

from labjury import Content, Item, State, is_content_type, register_content_type


def test_builtin_modalities_registered():
    for m in ["text", "json", "image", "audio", "metadata", "frame_sequence"]:
        assert is_content_type(m)


def test_register_new_content_type_without_core_change():
    register_content_type("heatmap")
    assert is_content_type("heatmap")


def test_content_with_unregistered_modality_raises():
    with pytest.raises(ValueError):
        Content("not_a_real_type", payload=b"")


def test_state_add_and_query():
    s = State()
    s.add(Content("text", "xin chào"))
    s.add(Content("image", b"\x89PNG"))
    assert s.has("text") and s.modalities() == {"text", "image"}
    assert s.get("text")[0].payload == "xin chào"
    assert s.get("audio") == []


def test_state_flags_mutable():
    s = State()
    s.flags.add("needs_semantic")
    assert "needs_semantic" in s.flags


def test_item_id_is_correlation_id():
    item = Item("item-42", raw={"text": "x"})
    assert item.id == "item-42"
