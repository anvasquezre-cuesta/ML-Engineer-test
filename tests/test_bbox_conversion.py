"""Unit tests for pixels_to_points and find_name_bounding_boxes (story 2.3).

Closes the checklist gap: the only DPI division (AD-4) and multi-word name box
merging have no direct unit tests, only route-level proxy assertions.
"""

import pytest

from app.services.bbox_service import pixels_to_points, find_name_bounding_boxes


class TestBboxConversion:
    """pixels_to_points: the single DPI division point (AD-4)."""

    def test_pixels_to_points_dpi_300(self):
        """AC-3: exact float expectations for 72/300 scaling."""
        words = [{
            "word": "Alice",
            "page": 0,
            "x": 150, "y": 300,
            "width": 75, "height": 15,
        }]
        result = pixels_to_points(words, dpi=300)
        assert len(result) == 1
        assert result[0]["x"] == pytest.approx(36.0)
        assert result[0]["y"] == pytest.approx(72.0)
        assert result[0]["width"] == pytest.approx(18.0)
        assert result[0]["height"] == pytest.approx(3.6)

    def test_pixels_to_points_dpi_200(self):
        """Different DPI: scale = 72/200 = 0.36."""
        words = [{
            "word": "Bob",
            "page": 1,
            "x": 100, "y": 200,
            "width": 50, "height": 10,
        }]
        result = pixels_to_points(words, dpi=200)
        assert result[0]["x"] == pytest.approx(36.0)
        assert result[0]["y"] == pytest.approx(72.0)
        assert result[0]["width"] == pytest.approx(18.0)
        assert result[0]["height"] == pytest.approx(3.6)


class TestNameBoxMatching:
    """find_name_bounding_boxes: multi-word merge, single word, absent name."""

    def test_single_word_name(self):
        """Single-word name found."""
        words = [
            {"word": "Hello", "page": 0, "x": 0, "y": 0, "width": 20, "height": 10},
            {"word": "Alice", "page": 0, "x": 30, "y": 0, "width": 30, "height": 10},
            {"word": "World", "page": 0, "x": 70, "y": 0, "width": 20, "height": 10},
        ]
        result = find_name_bounding_boxes("alice", words)
        assert len(result) == 1
        assert result[0]["name"] == "alice"
        assert result[0]["x"] == 30
        assert result[0]["width"] == 30

    def test_multi_word_merge(self):
        """AC-4: two-word name found as adjacent words → merged box."""
        words = [
            {"word": "Hello", "page": 0, "x": 0, "y": 0, "width": 20, "height": 10},
            {"word": "Alice", "page": 0, "x": 30, "y": 0, "width": 30, "height": 10},
            {"word": "Smith", "page": 0, "x": 70, "y": 0, "width": 35, "height": 10},
            {"word": "World", "page": 0, "x": 120, "y": 0, "width": 20, "height": 10},
        ]
        result = find_name_bounding_boxes("alice smith", words)
        assert len(result) == 1
        assert result[0]["name"] == "alice smith"
        # Merged box: x=30, y=0, width=30+35+gap=75, height=10
        assert result[0]["x"] == 30
        assert result[0]["y"] == 0
        assert result[0]["width"] == 75  # 30+30 to 70+35
        assert result[0]["height"] == 10

    def test_absent_name_empty_result(self):
        """AC-4: name not in word list → empty result."""
        words = [
            {"word": "Hello", "page": 0, "x": 0, "y": 0, "width": 20, "height": 10},
            {"word": "World", "page": 0, "x": 30, "y": 0, "width": 20, "height": 10},
        ]
        result = find_name_bounding_boxes("alice smith", words)
        assert result == []

    def test_empty_word_list(self):
        """AC-4: empty word list → empty result."""
        result = find_name_bounding_boxes("alice", [])
        assert result == []
