from labjury import Scorer


def test_fake_scorer_satisfies_protocol():
    class FakeScorer:
        accepts = frozenset({"*"})

        async def score(self, state, questions):
            return []

    assert isinstance(FakeScorer(), Scorer)


def test_object_missing_method_is_not_scorer():
    class NotScorer:
        accepts = frozenset({"*"})

    assert not isinstance(NotScorer(), Scorer)


def test_capabilities_readable():
    class ImageOnly:
        accepts = frozenset({"image"})

        async def score(self, state, questions):
            return []

    assert "image" in ImageOnly().accepts
