import json

import pytest

from labjury.secrets import Secret


def test_secret_masks_value():
    s = Secret("sk-supersecret")
    assert "sk-supersecret" not in repr(s)
    assert "sk-supersecret" not in str(s)
    assert "sk-supersecret" not in f"{s}" and "sk-supersecret" not in f"{s!r}"


def test_secret_reveal_returns_value():
    assert Secret("sk-supersecret").reveal() == "sk-supersecret"


def test_secret_not_json_serializable():
    with pytest.raises(TypeError):
        json.dumps(Secret("sk-supersecret"))


def test_secret_equality_and_hash():
    assert Secret("k") == Secret("k")
    assert Secret("k") != Secret("other")
    assert (Secret("k") == "k") is False
    assert hash(Secret("k")) == hash(Secret("k"))
    assert len({Secret("k"), Secret("k")}) == 1
