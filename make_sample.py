"""生成一份最小的「1.0 Tf」样本 PDF —— 零依赖，纯手写字节。

这个脚本存在的意义：让人亲眼看到 PDF 里确实写着 ``1.0 Tf``。

    BT /F1 1 Tf 12 0 0 12 60 760 Tm (...) Tj ET
              ^^^^^ 字号 1.0            ^^^^^^^^^ 矩阵里才是 12

如果不读 ``FPDFText_GetMatrix``，``FPDFText_GetFontSize`` 只会告诉你"1.0"。

跑法::

    python make_sample.py            # 写到 examples/one-pt-tf.pdf
    python make_sample.py out.pdf
"""
from __future__ import annotations

import sys
from pathlib import Path

# 三档写法并列，覆盖：矩阵缩放、直接字号、矩阵缩放 + 颜色、粗体、斜体、衬线
CONTENT = r"""BT /F1 1 Tf 12 0 0 12 60 760 Tm 0 0 0 rg (A  1.0 Tf  + 12x matrix  -> 12.0pt black) Tj ET
BT /F1 9 Tf 1 0 0 1 60 730 Tm (B  9 Tf    + identity      ->  9.0pt black) Tj ET
BT /F1 1 Tf 9 0 0 9 60 700 Tm 0 0 1 rg (C  1.0 Tf  + 9x  matrix  ->  9.0pt blue)  Tj ET
BT /F2 1 Tf 14 0 0 14 60 660 Tm 0 0 0 rg (D  1.0 Tf  + 14x matrix  -> 14.0pt bold)  Tj ET
BT /F4 1 Tf 11 0 0 11 60 630 Tm (E  1.0 Tf  + 11x matrix  -> 11.0pt italic) Tj ET
BT /F3 1 Tf 10 0 0 10 60 600 Tm (F  1.0 Tf  + 10x matrix  -> 10.0pt serif) Tj ET
"""


def build_pdf(content: str = CONTENT, page_w: int = 595, page_h: int = 842) -> bytes:
    """把一段内容流包成合法的单页 PDF，返回字节。"""
    stream = content.encode("latin-1")
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        (
            f"<</Type/Page/Parent 2 0 R/MediaBox[0 0 {page_w} {page_h}]"
            "/Resources<</Font<</F1 4 0 R/F2 5 0 R/F3 6 0 R/F4 7 0 R>>>>"
            "/Contents 8 0 R>>"
        ).encode(),
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/WinAnsiEncoding>>",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica-Bold/Encoding/WinAnsiEncoding>>",
        b"<</Type/Font/Subtype/Type1/BaseFont/Times-Roman/Encoding/WinAnsiEncoding>>",
        b"<</Type/Font/Subtype/Type1/BaseFont/Times-Italic/Encoding/WinAnsiEncoding>>",
        b"<</Length " + str(len(stream)).encode() + b">>stream\n" + stream + b"\nendstream",
    ]

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_pos = len(out)
    n = len(objects) + 1
    out += f"xref\n0 {n}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<</Size {n}/Root 1 0 R>>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode()
    return bytes(out)


def main(argv: list[str]) -> int:
    target = Path(argv[1]) if len(argv) > 1 else Path("examples/one-pt-tf.pdf")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(build_pdf())
    print(f"wrote {target}  ({target.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
