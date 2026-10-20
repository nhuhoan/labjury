import pytest

from labjury import Content, State
from labjury.router import NoRouteError, Route, Router


class ImageScorer:
    accepts = frozenset({"image"})

    async def score(self, state, questions):
        return []


class StarScorer:
    accepts = frozenset({"*"})

    async def score(self, state, questions):
        return []


class TextProposer:
    accepts = frozenset({"text"})

    async def propose(self, state, context):
        return []


def test_image_only_item_skips_proposer():
    s = State()
    s.add(Content("image", b"img"))
    route = Router(proposers=[TextProposer()], scorers=[ImageScorer()]).route(s)
    assert route.use_proposer is False and route.scorer.__class__ is ImageScorer


def test_needs_semantic_flag_forces_long_route():
    s = State()
    s.add(Content("image", b"img"))
    s.flags.add("needs_semantic")
    route = Router([TextProposer()], [ImageScorer(), StarScorer()]).route(s)
    assert route.use_proposer is True


def test_text_item_uses_proposer():
    s = State()
    s.add(Content("text", "ẩn ý khó hiểu"))
    route = Router([TextProposer()], [StarScorer()]).route(s)
    assert route.use_proposer is True


def test_no_matching_scorer_raises():
    s = State()
    s.add(Content("audio", b"wav"))
    with pytest.raises(NoRouteError):
        Router([], [ImageScorer()]).route(s)


def test_metadata_only_item_uses_proposer():
    # a non-visual item (json/metadata) must take the proposer route, not be
    # silently fast-pathed just because it has no "text" content
    s = State()
    s.add(Content("metadata", {"views": 1000}))
    route = Router([TextProposer()], [StarScorer()]).route(s)
    assert route.use_proposer is True


def test_frame_sequence_is_visual_fast_path():
    s = State()
    s.add(Content("frame_sequence", [b"f1", b"f2"]))
    route = Router([TextProposer()], [StarScorer()]).route(s)
    assert route.use_proposer is False
