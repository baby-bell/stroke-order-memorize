import pathlib
import re
import site
import xml.etree.ElementTree as ET

_SVG_NS = "http://www.w3.org/2000/svg"
_E = f"{{{_SVG_NS}}}"


def svg_path_for(char: str) -> pathlib.Path:
    """Return the canonical (non-Kaisho) KanjiVG SVG path for a single character."""
    codepoint = format(ord(char), "05x")
    for sp in site.getsitepackages():
        p = pathlib.Path(sp) / "kanji" / f"{codepoint}.svg"
        # Skip variant files (e.g. 04e00-Kaisho.svg); canonical file has no hyphen
        if p.exists() and "-" not in p.stem:
            return p
    raise FileNotFoundError(f"No KanjiVG SVG for {char!r} (U+{codepoint.upper()})")


def _matrix_xy(transform: str) -> tuple[str, str]:
    """Extract x, y from 'matrix(1 0 0 1 x y)'."""
    nums = re.findall(r"[-\d.]+", transform)
    if len(nums) >= 6:
        return nums[4], nums[5]
    return "0", "0"


def parse_strokes(char: str) -> list[tuple[str, str, str, str]]:
    """
    Return stroke data for a character as a list of
    (path_d, label_text, label_x, label_y) tuples in stroke order.
    """
    svg_file = svg_path_for(char)
    codepoint = format(ord(char), "05x")
    tree = ET.parse(svg_file)
    root = tree.getroot()

    paths: list[str] = []
    for g in root.iter(f"{_E}g"):
        if g.get("id") == f"kvg:StrokePaths_{codepoint}":
            for path_el in g.iter(f"{_E}path"):
                paths.append(path_el.get("d", ""))
            break

    labels: list[tuple[str, str, str]] = []
    for g in root.iter(f"{_E}g"):
        if g.get("id") == f"kvg:StrokeNumbers_{codepoint}":
            for text_el in g.iter(f"{_E}text"):
                x, y = _matrix_xy(text_el.get("transform", ""))
                labels.append((text_el.text or "", x, y))
            break

    return [(d, lbl, x, y) for d, (lbl, x, y) in zip(paths, labels)]
