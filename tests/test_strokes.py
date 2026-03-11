import pytest
from app.strokes import svg_path_for, parse_strokes


class TestSvgPathFor:
    def test_finds_svg_for_ichi(self):
        path = svg_path_for("一")
        assert path.exists()
        assert path.name == "04e00.svg"

    def test_finds_svg_for_hi(self):
        path = svg_path_for("日")
        assert path.exists()
        assert path.name == "065e5.svg"

    def test_raises_for_unknown_char(self):
        # Private-use area character not in KanjiVG
        with pytest.raises(FileNotFoundError):
            svg_path_for("\ue000")


class TestParseStrokes:
    def test_ichi_has_one_stroke(self):
        strokes = parse_strokes("一")
        assert len(strokes) == 1

    def test_stroke_tuple_has_four_elements(self):
        path_d, label, x, y = parse_strokes("一")[0]
        assert path_d.startswith("M")   # SVG path Move command
        assert label == "1"
        float(x)  # must be numeric
        float(y)

    def test_hi_has_four_strokes(self):
        strokes = parse_strokes("日")
        assert len(strokes) == 4

    def test_labels_are_sequential(self):
        strokes = parse_strokes("日")
        labels = [s[1] for s in strokes]
        assert labels == ["1", "2", "3", "4"]
