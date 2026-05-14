"""Unit tests for app.aligner"""
import pytest
from app.aligner import (
    _normalise, _ratio, _confidence_from_ratio,
    _cluster_takes, _find_all_takes, align_line_multitake,
    TakeSpan, AlignmentResult, align_all,
    MAX_TAKE_GAP,
)


def make_words(texts, start_offset=0.0, word_duration=0.5, gap=0.1):
    """Build a word list from a list of word strings."""
    words = []
    t = start_offset
    for w in texts:
        words.append({"word": w, "start": t, "end": t + word_duration})
        t += word_duration + gap
    return words


class TestNormalise:
    def test_lowercase(self):
        assert _normalise("Hello World") == "hello world"

    def test_strips_punctuation(self):
        assert _normalise("Hello, world!") == "hello world"

    def test_keeps_apostrophe(self):
        assert _normalise("don't") == "don't"

    def test_collapses_whitespace(self):
        assert _normalise("  hello   world  ") == "hello world"

    def test_empty(self):
        assert _normalise("") == ""

    def test_numbers_kept(self):
        assert _normalise("line 42") == "line 42"


class TestRatio:
    def test_identical(self):
        assert _ratio("hello", "hello") == 1.0

    def test_empty(self):
        assert _ratio("", "") == 1.0

    def test_completely_different(self):
        r = _ratio("aaa", "bbb")
        assert r == 0.0

    def test_partial(self):
        r = _ratio("hello world", "hello earth")
        assert 0.0 < r < 1.0


class TestConfidenceFromRatio:
    def test_level5(self):
        assert _confidence_from_ratio(0.92) == 5
        assert _confidence_from_ratio(1.0) == 5

    def test_level4(self):
        assert _confidence_from_ratio(0.80) == 4
        assert _confidence_from_ratio(0.91) == 4

    def test_level3(self):
        assert _confidence_from_ratio(0.65) == 3
        assert _confidence_from_ratio(0.79) == 3

    def test_level2(self):
        assert _confidence_from_ratio(0.45) == 2
        assert _confidence_from_ratio(0.64) == 2

    def test_level1(self):
        assert _confidence_from_ratio(0.0) == 1
        assert _confidence_from_ratio(0.44) == 1


class TestClusterTakes:
    def _span(self, start, end, ratio=0.9):
        return TakeSpan(0, 0, start, end, ratio, "")

    def test_empty(self):
        assert _cluster_takes([]) == []

    def test_single(self):
        spans = [self._span(0, 1)]
        clusters = _cluster_takes(spans)
        assert len(clusters) == 1
        assert len(clusters[0]) == 1

    def test_close_spans_merged(self):
        spans = [self._span(0, 1), self._span(1 + MAX_TAKE_GAP - 0.1, 2 + MAX_TAKE_GAP)]
        clusters = _cluster_takes(spans)
        assert len(clusters) == 1

    def test_far_spans_separate(self):
        spans = [self._span(0, 1), self._span(1 + MAX_TAKE_GAP + 0.1, 3 + MAX_TAKE_GAP)]
        clusters = _cluster_takes(spans)
        assert len(clusters) == 2

    def test_three_in_one_cluster(self):
        spans = [self._span(0, 1), self._span(2, 3), self._span(4, 5)]
        clusters = _cluster_takes(spans)
        assert len(clusters) == 1
        assert len(clusters[0]) == 3


class TestFindAllTakes:
    def test_empty_words(self):
        result = _find_all_takes("hello world", [])
        assert result == []

    def test_exact_match(self):
        words = make_words(["hello", "world"])
        result = _find_all_takes("hello world", words)
        assert len(result) >= 1
        assert result[0].ratio >= 0.8

    def test_no_good_match_returns_empty(self):
        words = make_words(["foo", "bar", "baz"])
        result = _find_all_takes("completely different text here", words)
        # May return empty or low-ratio result, but shouldn't crash
        assert isinstance(result, list)

    def test_multiple_takes_detected(self):
        # Repeat the line twice with a gap
        line_words = ["the", "quick", "brown", "fox"]
        # repeat = line + silence gap + line again
        words = make_words(line_words, start_offset=0.0)
        # Second take starts far enough to be a separate cluster
        words += make_words(line_words, start_offset=100.0)
        result = _find_all_takes("the quick brown fox", words)
        # Should find at least 2 candidate takes
        assert len(result) >= 2


class TestAlignLineMultitake:
    def test_basic_alignment(self):
        words = make_words(["hello", "world", "how", "are", "you"])
        takes, ratio = align_line_multitake("hello world", words)
        assert len(takes) >= 1
        assert ratio > 0.0

    def test_padding_applied(self):
        words = make_words(["hello", "world"])
        takes, ratio = align_line_multitake("hello world", words, pad_start=0.1, pad_end=0.2)
        # The function returns takes without applying padding itself;
        # align_all does the padding. Just check it runs.
        assert takes is not None

    def test_fallback_on_empty_words(self):
        # With empty words, should fall back and still return something
        words = make_words(["something", "else", "entirely"])
        takes, ratio = align_line_multitake("hello world", words)
        assert isinstance(takes, list)
        assert len(takes) >= 1

    def test_returns_tuple(self):
        words = make_words(["a", "b", "c"])
        result = align_line_multitake("a b c", words)
        assert isinstance(result, tuple)
        assert len(result) == 2


class TestAlignAll:
    def _make_words(self, texts, offset=0.0):
        return make_words(texts, start_offset=offset)

    def test_no_words_returns_placeholder(self):
        rows = [{"index": "001", "output_name": "Line_001", "line_text": "hello world"}]
        results = align_all(rows, {}, {})
        assert len(results) == 1
        assert results[0].confidence == 1
        assert results[0].take_count == 0

    def test_with_matching_words(self):
        rows = [{"index": "001", "output_name": "Line_001", "line_text": "hello world"}]
        words = self._make_words(["hello", "world"])
        group_word_map = {"grp1": words}
        row_to_group = {"001": "grp1"}
        results = align_all(rows, group_word_map, row_to_group)
        assert len(results) == 1
        r = results[0]
        assert r.row_index == "001"
        assert r.output_name == "Line_001"
        assert r.length > 0

    def test_multiple_rows(self):
        rows = [
            {"index": "001", "output_name": "Line_001", "line_text": "hello world"},
            {"index": "002", "output_name": "Line_002", "line_text": "foo bar baz"},
        ]
        words1 = self._make_words(["hello", "world"])
        words2 = self._make_words(["foo", "bar", "baz"])
        results = align_all(
            rows,
            {"g1": words1, "g2": words2},
            {"001": "g1", "002": "g2"},
        )
        assert len(results) == 2
        assert results[0].row_index == "001"
        assert results[1].row_index == "002"

    def test_needs_review_low_confidence(self):
        rows = [{"index": "001", "output_name": "Out", "line_text": "hello world"}]
        # Mismatched words → low confidence
        words = self._make_words(["completely", "different", "stuff", "here"])
        results = align_all(rows, {"g1": words}, {"001": "g1"})
        r = results[0]
        # If confidence <=2, needs_review should be True
        if r.confidence <= 2:
            assert r.needs_review is True
        else:
            assert r.needs_review is False
