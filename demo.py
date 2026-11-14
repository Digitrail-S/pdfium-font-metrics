"""See what `1.0 Tf` actually looks like.

    python demo.py                     # uses the bundled examples/one-pt-tf.pdf
    python demo.py your.pdf            # your own PDF
    python demo.py your.pdf 3          # specific page
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pdfium_font import PageText  # noqa: E402

DEFAULT = str(Path(__file__).resolve().parent / "examples" / "one-pt-tf.pdf")


def ensure_sample(path: str) -> None:
    p = Path(path)
    if p.exists():
        return
    # The sample is generated from hand-built bytes, so it needs no dependencies.
    sys.path.insert(0, str(Path(__file__).parent))
    from make_sample import build_pdf
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(build_pdf())
    print(f"(generated {p})\n")


def main(argv: list[str]) -> int:
    path = argv[1] if len(argv) > 1 else DEFAULT
    page = int(argv[2]) if len(argv) > 2 else 0
    ensure_sample(path)

    with PageText(path, page) as pt:
        print(f"file : {path}")
        print(f"page : {page}   chars: {pt.count()}\n")

        # ---- dissect one character ----
        for ch in pt.chars(skip_blank=True):
            if abs(ch.size - ch.raw_size) > 0.01:
                a, b, c, d, e, f = ch.matrix
                print("one character, in full:")
                print(f"  text      = {ch.text!r}")
                print(f"  raw_size  = {ch.raw_size:.3f}        <- FPDFText_GetFontSize only gives you this")
                print(f"  matrix    = [{a:.3f} {b:.3f} {c:.3f} {d:.3f} {e:.3f} {f:.3f}]")
                print(f"  scale     = sqrt(|a|*|d|) = {ch.scale:.3f}")
                print(f"  size      = raw_size * scale = {ch.size:.3f}   <- the real font size")
                print()
                break

        # ---- per-page run table ----
        head = (f"{'#':>2}  {'raw':>6} {'size':>7} {'scale':>7} {'w':>4} {'it':>2}  "
                f"{'font':<16} {'color':<16} text")
        print(head)
        print("-" * (len(head) + 20))
        i = 0
        for r in pt.runs():
            if not r["text"].strip():
                continue
            i += 1
            rgb = "(%3d,%3d,%3d)" % r["color"][:3]
            text = r["text"] if len(r["text"]) <= 44 else r["text"][:41] + "..."
            print(f"{i:2d}  {r['raw_size']:6.2f} {r['size']:7.2f} {r['scale']:7.3f} "
                  f"{r['weight']:4d} {int(r['italic']):2d}  {r['font']:<16} {rgb:<16} {text}")

        # ---- summary ----
        chars = list(pt.chars(skip_blank=True))
        total = len(chars)
        ones = sum(1 for ch in chars if abs(ch.raw_size - 1.0) < 1e-6)
        if total:
            print(f"\nraw_size == 1.0 : {ones}/{total} chars ({100.0 * ones / total:.1f}%) "
                  f"-> size alone would be 1.0 for these")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
