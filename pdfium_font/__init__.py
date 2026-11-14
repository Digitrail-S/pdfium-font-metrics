"""pdfium_font - the character-level font dimensions that pypdfium2 does not expose.

pdfium's C API has always provided these functions, but pypdfium2's high-level
``PdfTextPage`` does not wrap them:

    FPDFText_GetFontSize      size in text space (real PDFs often store 1.0; the
                              actual size comes from matrix scaling)
    FPDFText_GetMatrix        effective transform matrix of the character
    FPDFText_GetFontInfo      font name (may carry a six-letter subset prefix such
                              as ``YMVEVT+``) plus descriptor flags
    FPDFText_GetFontWeight    raw weight value (not a CSS weight, see
                              ``_normalize_weight``)
    FPDFText_GetFillColor     RGBA fill colour
    FPDFText_GetLooseCharBox  character box by advance width
    FPDFText_GetCharOrigin    character origin (baseline start)

``FPDFText_GetMatrix`` is the one that matters. ``FPDFText_GetFontSize`` returns the size in
text space, and a large share of real documents write ``1.0 Tf`` and put the scaling on
``Tm`` - read the size without the matrix and you get ``1.0``, not the real size.

Usage::

    from pdfium_font import PageText

    with PageText("doc.pdf", page_index=0) as pt:
        for ch in pt.chars():
            print(ch.text, ch.size, ch.font, ch.weight, ch.color)

    # or aggregate into runs (same font / size / weight / colour)
    for run in pt.runs():
        print(run["size"], run["font"], run["text"])
"""
from __future__ import annotations

import ctypes
import math
import re
from dataclasses import dataclass

import pypdfium2 as pdfium
import pypdfium2.raw as C

__all__ = ["CharFont", "PageText"]

# Font descriptor flag bits from the PDF specification (PDF 32000-1, 9.8.1).
FLAG_FIXED_PITCH = 1 << 0
FLAG_SERIF = 1 << 1
FLAG_SYMBOLIC = 1 << 2
FLAG_SCRIPT = 1 << 3
FLAG_NONSYMBOLIC = 1 << 5
FLAG_ITALIC = 1 << 6
FLAG_ALLCAP = 1 << 16
FLAG_SMALLCAP = 1 << 17
FLAG_FORCE_BOLD = 1 << 18

# Subset prefix: six uppercase ASCII letters followed by '+', e.g. "ABCDEF+FontName".
_SUBSET_RE = re.compile(r"^[A-Z]{6}\+")


@dataclass(frozen=True)
class CharFont:
    """One character together with its font dimensions.

    Attributes:
        text: The character itself.
        bbox: Character box hugging the glyph, ``(x0, y0, x1, y1)`` in PDF user space.
        size: Effective size in device space (pt), already scaled by the matrix.
            This is the value to use.
        size_h: Horizontal equivalent size; governs glyph width and overflow checks.
        size_v: Vertical equivalent size; governs line height.
        font: Font name with the six-letter subset prefix stripped.
        weight: Weight normalised to 100-900 (see ``_normalize_weight``).
        italic: Whether the glyph is italic or oblique.
        color: Fill colour ``(r, g, b, a)``.
        raw_size: Raw ``FPDFText_GetFontSize`` value, for diagnostics.
        scale: Scale factor derived from the matrix; ``size == raw_size * scale``.
        matrix: Effective text matrix ``(a, b, c, d, e, f)``.
        loose: Character box computed from advance width, closer to the layout slot
            than ``bbox``.
        origin: Character origin (baseline start), used for line clustering.
    """

    text: str
    bbox: tuple[float, float, float, float]
    size: float
    size_h: float
    size_v: float
    font: str
    weight: int
    italic: bool
    color: tuple[int, int, int, int]
    raw_size: float
    scale: float
    matrix: tuple[float, float, float, float, float, float]
    loose: tuple[float, float, float, float]
    origin: tuple[float, float]


def _strip_subset(name: str) -> str:
    return _SUBSET_RE.sub("", name)


def _weight_from_name(name: str) -> int:
    n = name.lower()
    for key, w in (("thin", 100), ("extralight", 200), ("ultralight", 200),
                   ("light", 300), ("regular", 400), ("book", 400),
                   ("medium", 500), ("semibold", 600), ("demibold", 600),
                   ("extrabold", 800), ("ultrabold", 800),
                   ("black", 900), ("heavy", 900), ("bold", 700)):
        if key in n:
            return w
    return 0


def _normalize_weight(font: str, pdfium_weight: int) -> int:
    """Map pdfium's raw weight onto a CSS-style 100-900 value.

    ``FPDFText_GetFontWeight`` returns the stemV-derived weight of the font
    descriptor, which is **not** a CSS weight. Within one family, Roman and Bold may
    differ only by 220 vs 235, so using the raw number directly puts everything below
    400. The font name is therefore checked first; the numeric value is only a coarse
    fallback.
    """
    by_name = _weight_from_name(font)
    if by_name:
        return by_name
    w = pdfium_weight or 0
    if w <= 0:
        return 400
    if w >= 600:
        return 700
    if w >= 500:
        return 500
    if w <= 200:
        return 300
    return 400


class PageText:
    """The character stream of one page, with font dimensions. Use as a context manager.

    Args:
        source: A path, bytes, or an already-open ``PdfDocument``.
        page_index: Zero-based page index.
    """

    def __init__(self, source, page_index: int = 0):
        self._doc = pdfium.PdfDocument(source)
        self._page = self._doc[page_index]
        self._init_page()

    @classmethod
    def from_page(cls, page) -> "PageText":
        """Reuse an already-open ``PdfPage`` instead of reopening the document."""
        self = cls.__new__(cls)
        self._doc = None
        self._page = page
        self._init_page()
        return self

    def _init_page(self):
        self._tp = self._page.get_textpage()
        self._ptr = self._tp.raw
        self._buf = ctypes.create_string_buffer(256)
        self._flags = ctypes.c_int()
        self._mat = C.FS_MATRIX()
        self._rgba = [ctypes.c_uint() for _ in range(4)]

    # ---- lifecycle ----
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def close(self):
        self._tp.close()
        if self._doc is not None:
            self._doc.close()

    # ---- single character ----
    def count(self) -> int:
        return self._tp.count_chars()

    def char(self, i: int) -> CharFont | None:
        text = self._tp.get_text_range(index=i, count=1)
        if not text:
            return None
        x0, y0, x1, y1 = self._tp.get_charbox(i)

        ox, oy = ctypes.c_double(0.0), ctypes.c_double(0.0)
        if C.FPDFText_GetCharOrigin(self._ptr, i, ctypes.byref(ox), ctypes.byref(oy)):
            origin = (ox.value, oy.value)
        else:
            origin = (x0, y0)

        lb = C.FS_RECTF()
        if C.FPDFText_GetLooseCharBox(self._ptr, i, ctypes.byref(lb)):
            loose = (lb.left, lb.bottom, lb.right, lb.top)
            if loose[2] <= loose[0]:
                loose = (x0, y0, x1, y1)
        else:
            loose = (x0, y0, x1, y1)

        raw_size = C.FPDFText_GetFontSize(self._ptr, i)
        C.FPDFText_GetMatrix(self._ptr, i, ctypes.byref(self._mat))
        m = self._mat
        matrix = (m.a, m.b, m.c, m.d, m.e, m.f)

        # a and d are the horizontal and vertical scale. They differ under
        # non-uniform scaling (common in some Office / WPS exports), so take the
        # geometric mean sqrt(|a|*|d|), which matches PyMuPDF's span["size"].
        #
        # A pure rotation matrix is [0 b; c 0], i.e. a = d = 0, where the geometric
        # mean degenerates to 1.0 and the size would collapse to raw_size. So fall
        # back to sqrt(|det|) when the diagonal is zero. For diagonal matrices
        # sqrt(|det|) == sqrt(|a|*|d|), so this only affects rotated or sheared text;
        # horizontal text is untouched.
        ax, dy = abs(m.a), abs(m.d)
        det = m.a * m.d - m.b * m.c
        if ax and dy:
            scale = math.sqrt(ax * dy)
        elif abs(det) > 1e-12:
            scale = math.sqrt(abs(det))
        else:
            scale = 1.0
        size = raw_size * scale

        self._flags = ctypes.c_int()
        C.FPDFText_GetFontInfo(self._ptr, i,
                               ctypes.cast(self._buf, ctypes.c_void_p),
                               len(self._buf), ctypes.byref(self._flags))
        font = _strip_subset(self._buf.value.decode("utf-8", "replace"))

        weight = _normalize_weight(font, C.FPDFText_GetFontWeight(self._ptr, i))
        italic = (bool(self._flags.value & FLAG_ITALIC)
                  or "italic" in font.lower()
                  or "oblique" in font.lower())

        for c in self._rgba:
            c.value = 0
        ok = C.FPDFText_GetFillColor(self._ptr, i,
                                     *[ctypes.byref(c) for c in self._rgba])
        color = tuple(c.value for c in self._rgba) if ok else (0, 0, 0, 255)

        return CharFont(
            text=text,
            bbox=(x0, y0, x1, y1),
            size=size,
            size_h=raw_size * (ax or scale),
            size_v=raw_size * (dy or scale),
            font=font,
            weight=weight,
            italic=italic,
            color=color,
            raw_size=raw_size,
            scale=scale,
            matrix=matrix,
            loose=loose,
            origin=origin,
        )

    def chars(self, skip_blank: bool = False):
        """Yield ``CharFont`` per character."""
        for i in range(self.count()):
            c = self.char(i)
            if c is None:
                continue
            if skip_blank and not c.text.strip():
                continue
            yield c

    # ---- aggregation ----
    def runs(self):
        """Group adjacent characters with identical font attributes into one run.

        The grouping key is ``(font, size, weight, italic, color)``, matching the
        span concept used by layout code.
        """
        cur = None
        for c in self.chars():
            key = (c.font, round(c.size, 2), c.weight, c.italic, c.color)
            if cur and cur["key"] == key:
                cur["chars"].append(c)
                x0, y0, x1, y1 = cur["bbox"]
                cur["bbox"] = (min(x0, c.bbox[0]), min(y0, c.bbox[1]),
                               max(x1, c.bbox[2]), max(y1, c.bbox[3]))
            else:
                if cur:
                    yield _finish_run(cur)
                cur = {"key": key, "chars": [c], "bbox": c.bbox}
        if cur:
            yield _finish_run(cur)


def _finish_run(cur) -> dict:
    first = cur["chars"][0]
    return {
        "text": "".join(x.text for x in cur["chars"]),
        "bbox": cur["bbox"],
        "font": first.font,
        "size": first.size,
        "raw_size": first.raw_size,
        "scale": first.scale,
        "weight": first.weight,
        "italic": first.italic,
        "color": first.color,
        "n": len(cur["chars"]),
    }
