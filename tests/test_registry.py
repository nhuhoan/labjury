import pytest

from labjury import available, clear, get, load_entry_points, register


def test_register_and_get():
    clear()
    register("scorers", "fake", lambda: "SCORER")
    assert get("scorers", "fake") == "SCORER"
    assert "fake" in available("scorers")


def test_get_unknown_raises():
    clear()
    with pytest.raises(KeyError):
        get("scorers", "missing")


def test_load_entry_points_registers(monkeypatch):
    clear()

    class FakeEP:
        def __init__(self, name, value):
            self.name = name
            self._value = value

        def load(self):
            return self._value

    class FakeEntryPoints:
        def select(self, group):
            if group == "labjury.scorers":
                return [FakeEP("fake_ep", lambda: "LOADED")]
            return []

    monkeypatch.setattr("labjury.registry.entry_points", lambda: FakeEntryPoints())
    load_entry_points()
    assert "fake_ep" in available("scorers")
    assert get("scorers", "fake_ep") == "LOADED"
