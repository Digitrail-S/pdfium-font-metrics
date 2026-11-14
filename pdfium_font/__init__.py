"""pdfium_font —— pypdfium2 缺失的字符级字体维度。

pdfium 的 C API 一直都有这些函数，但 pypdfium2 的 ``PdfTextPage`` 高层类没有封装：

    FPDFText_GetFontSize     文字空间字号（PDF 里常用 1.0，真实大小靠矩阵缩放）
    FPDFText_GetMatrix       字符的有效变换矩阵
    FPDFText_GetFontInfo     字体名（可能带 6 位子集前缀，如 ``YMVEVT+``）+ 描述符 flags
    FPDFText_GetFontWeight   原始 weight 值（不是 CSS 字重，见 ``_normalize_weight``）
    FPDFText_GetFillColor    文字填充色 RGBA
    FPDFText_GetLooseCharBox ``advance`` 宽度意义上的字符框
    FPDFText_GetCharOrigin   字符原点（基线起点）

其中 **`FPDFText_GetMatrix` 是最关键的一个**。`FPDFText_GetFontSize` 返回的是文本空间
字号，而 PDF 里大量文档写的是 ``1.0 Tf`` 再去 ``Tm`` 上做缩放 —— 不乘矩阵,拿到的就是
``1.0``，不是真实字号。

用法::

    from pdfium_font import PageText

    with PageText("doc.pdf", page_index=0) as pt:
        for ch in pt.chars():
            print(ch.text, ch.size, ch.font, ch.weight, ch.color)

    # 或按 run 聚合（同字体 / 同字号 / 同字重 / 同色）
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

# PDF 规范里的字体描述符 flags 位（PDF 32000-1 §9.8.1）
FLAG_FIXED_PITCH = 1 << 0
FLAG_SERIF = 1 << 1
FLAG_SYMBOLIC = 1 << 2
FLAG_SCRIPT = 1 << 3
FLAG_NONSYMBOLIC = 1 << 5
FLAG_ITALIC = 1 << 6
FLAG_ALLCAP = 1 << 16
FLAG_SMALLCAP = 1 << 17
FLAG_FORCE_BOLD = 1 << 18

# 子集前缀：6 个 ASCII 大写 + '+'（"ABCDEF+FontName"）
_SUBSET_RE = re.compile(r"^[A-Z]{6}\+")


@dataclass(frozen=True)
class CharFont:
    """一个字符，连同它的字体维度。

    Attributes:
        text: 字符本身。
        bbox: 紧贴字形的字符框 ``(x0, y0, x1, y1)``，PDF 用户空间。
        size: 设备空间有效字号（pt），已乘矩阵缩放。**这是你要用的那个**。
        size_h: 水平方向等效字号，影响字宽与溢出判断。
        size_v: 垂直方向等效字号，影响行高。
        font: 字体名，已剥掉 6 位子集前缀。
        weight: 归一化到 100~900 的字重（见 ``_normalize_weight``）。
        italic: 是否斜体。
        color: 填充色 ``(r, g, b, a)``。
        raw_size: ``FPDFText_GetFontSize`` 原值，诊断用。
        scale: 从矩阵推出的缩放因子，``size == raw_size * scale``。
        matrix: 字符有效变换矩阵 ``(a, b, c, d, e, f)``。
        loose: 按 ``advance`` 计算的字符框，比 ``bbox`` 更接近排版占位。
        origin: 字符原点（基线起点），行聚类靠它。
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
    """把 pdfium 的原始 weight 归一化成 CSS 风格的 100~900。

    ``FPDFText_GetFontWeight`` 返回的是字体描述符里的 stemV 系粗值，**不是 CSS 字重**。
    同一族里 Roman / Bold 的差别可能只是 220 → 235，直接当 CSS 用会全被当成 400 以下。
    所以优先看字体名，名字判不出来才用数值粗分档。
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
    """一页的字符流 + 字体维度。用作上下文管理器。

    Args:
        source: 文件路径、bytes 或已打开的 ``PdfDocument``。
        page_index: 页序号，从 0 开始。
    """

    def __init__(self, source, page_index: int = 0):
        self._doc = pdfium.PdfDocument(source)
        self._page = self._doc[page_index]
        self._init_page()

    @classmethod
    def from_page(cls, page) -> "PageText":
        """复用一个已打开的 ``PdfPage``，避免反复开关文档。"""
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

    # ---- 生命周期 ----
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def close(self):
        self._tp.close()
        if self._doc is not None:
            self._doc.close()

    # ---- 单字符 ----
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

        # a/d 分别是水平/垂直缩放。非等比缩放（部分 Office / WPS 导出常见）时两者不等，
        # 取几何平均 sqrt(|a|·|d|)，与 PyMuPDF 的 span["size"] 口径一致。
        #
        # ⚠️ 纯旋转矩阵是 [0 b; c 0]，a = d = 0 ⇒ 几何平均退化成 1.0，字号会变成
        #    raw_size 本身。所以对角为 0 时改走 sqrt(|det|)。对角矩阵下
        #    sqrt(|det|) ≡ sqrt(|a|·|d|)，因此这条只影响旋转/切变，横排文本不受影响。
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
        """逐字符产出 ``CharFont``。"""
        for i in range(self.count()):
            c = self.char(i)
            if c is None:
                continue
            if skip_blank and not c.text.strip():
                continue
            yield c

    # ---- 聚合 ----
    def runs(self):
        """相邻且字体属性完全相同的字符聚成一个 run。

        判定键是 ``(font, size, weight, italic, color)``，与排版层的 span 概念对应。
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
