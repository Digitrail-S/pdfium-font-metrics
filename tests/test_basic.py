"""端到端测试：用 make_sample.py 生成的样本反查每个维度。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from make_sample import build_pdf  # noqa: E402
from pdfium_font import PageText, _strip_subset  # noqa: E402


@pytest.fixture(scope="module")
def sample(tmp_path_factory) -> str:
    p = tmp_path_factory.mktemp("samples") / "one-pt-tf.pdf"
    p.write_bytes(build_pdf())
    return str(p)


@pytest.fixture(scope="module")
def runs(sample):
    with PageText(sample, 0) as pt:
        return [r for r in pt.runs() if r["text"].strip()]


def test_sample_opens(sample):
    with PageText(sample, 0) as pt:
        assert pt.count() > 100


def test_matrix_scaled_size(runs):
    """1.0 Tf + 12x 矩阵 -> 12pt。raw_size 仍是 1.0。"""
    r = runs[0]
    assert r["raw_size"] == pytest.approx(1.0)
    assert r["scale"] == pytest.approx(12.0)
    assert r["size"] == pytest.approx(12.0)
    assert r["text"].startswith("A")


def test_direct_size_needs_no_matrix(runs):
    """9 Tf + 单位矩阵 -> 9pt，scale 必须是 1。"""
    r = runs[1]
    assert r["raw_size"] == pytest.approx(9.0)
    assert r["scale"] == pytest.approx(1.0)
    assert r["size"] == pytest.approx(9.0)


def test_fill_color(runs):
    """第三行是蓝色。"""
    assert tuple(runs[2]["color"]) == (0, 0, 255, 255)


def test_weight_from_font_name(runs):
    """Helvetica-Bold 的 pdfium weight 不可信，得靠字体名归一化成 700。"""
    bold = next(r for r in runs if r["font"] == "Helvetica-Bold")
    assert bold["weight"] == 700
    regular = next(r for r in runs if r["font"] == "Helvetica")
    assert regular["weight"] == 400


def test_italic_flag(runs):
    italic = next(r for r in runs if r["font"] == "Times-Italic")
    assert italic["italic"] is True


def test_matrix_exposed(sample):
    """matrix 必须原样暴露 a/b/c/d/e/f。"""
    with PageText(sample, 0) as pt:
        ch = next(c for c in pt.chars(skip_blank=True) if c.text == "A")
    a, b, c, d, e, f = ch.matrix
    assert a == pytest.approx(12.0) and b == pytest.approx(0.0)
    assert c == pytest.approx(0.0) and d == pytest.approx(12.0)
    assert (e, f) == pytest.approx((60.0, 760.0))


def test_size_h_size_v_agree_when_uniform(sample):
    """等比缩放时水平/垂直等效字号应相等。"""
    with PageText(sample, 0) as pt:
        ch = next(c for c in pt.chars(skip_blank=True) if c.text == "A")
    assert ch.size_h == pytest.approx(ch.size_v)


def test_subset_prefix_stripped():
    assert _strip_subset("YMVEVT+Arial") == "Arial"
    assert _strip_subset("Helvetica") == "Helvetica"
    # 只有 6 个大写字母 + 加号才算子集前缀
    assert _strip_subset("ABC+Def") == "ABC+Def"


def test_scan_pdf_has_no_chars(tmp_path):
    """零字节层的 PDF：count() 为 0，不应抛异常。"""
    p = tmp_path / "blank.pdf"
    p.write_bytes(build_pdf(""))
    with PageText(str(p), 0) as pt:
        assert pt.count() == 0
        assert list(pt.chars()) == []
