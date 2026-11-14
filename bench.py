"""Count how many characters in a PDF need the text matrix for a correct font size.

    python bench.py                          # bundled sample
    python bench.py a.pdf b.pdf              # several files
    python bench.py ~/Documents/pdfs         # a directory (recursive *.pdf)
    python bench.py big.pdf --pages 20       # first 20 pages only

This is the script behind the numbers in the README; rerun it to check them.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pypdfium2 as pdfium  # noqa: E402
from pdfium_font import PageText  # noqa: E402

TOL = 0.01  # tolerance for "the matrix actually changed the size"


def collect(targets: list[str]) -> list[Path]:
    out: list[Path] = []
    for t in targets:
        p = Path(t).expanduser()
        if p.is_dir():
            out.extend(sorted(p.rglob("*.pdf")))
        elif p.exists():
            out.append(p)
        else:
            print(f"! not found: {t}", file=sys.stderr)
    return out


def stat_file(path: Path, max_pages: int) -> dict:
    doc = pdfium.PdfDocument(str(path))
    n_pages = len(doc)
    pages = min(n_pages, max_pages) if max_pages > 0 else n_pages
    chars = ones = scaled = colored = 0
    fonts: set[str] = set()
    for pi in range(pages):
        with PageText.from_page(doc[pi]) as pt:
            for ch in pt.chars(skip_blank=True):
                chars += 1
                if abs(ch.raw_size - 1.0) < 1e-6:
                    ones += 1
                if abs(ch.scale - 1.0) > TOL:
                    scaled += 1
                if tuple(ch.color[:3]) != (0, 0, 0):
                    colored += 1
                if ch.font:
                    fonts.add(ch.font)
    doc.close()
    return dict(page=pages, n_page=n_pages, chars=chars, ones=ones,
                scaled=scaled, colored=colored, fonts=len(fonts))


def main(argv: list[str]) -> int:
    max_pages = 0
    args: list[str] = []
    i = 0
    while i < len(argv[1:]):
        a = argv[1 + i]
        if a == "--pages" and i + 2 <= len(argv[1:]):
            max_pages = int(argv[2 + i])
            i += 2
            continue
        if not a.startswith("--"):
            args.append(a)
        i += 1

    if not args:
        args = [str(Path(__file__).resolve().parent / "examples" / "one-pt-tf.pdf")]
        if not Path(args[0]).exists():
            sys.path.insert(0, str(Path(__file__).parent))
            from make_sample import build_pdf
            Path(args[0]).parent.mkdir(parents=True, exist_ok=True)
            Path(args[0]).write_bytes(build_pdf())

    files = collect(args)
    if not files:
        print("no pdf found", file=sys.stderr)
        return 1

    head = (f"{'file':<34} {'pages':>5} {'chars':>8} {'fs=1.0':>8} "
            f"{'scaled':>8} {'colored':>8} {'fonts':>5}")
    print(head)
    print("-" * len(head))

    tot = dict(chars=0, ones=0, scaled=0, colored=0)
    for f in files:
        try:
            s = stat_file(f, max_pages)
        except Exception as e:
            print(f"{f.name[:32]:<34}  ERROR {type(e).__name__}: {e}")
            continue
        n = max(s["chars"], 1)
        pct = lambda k: f"{100.0 * s[k] / n:7.1f}%"
        page_label = (f"{s['page']}" if s["page"] == s["n_page"]
                      else f"{s['page']}/{s['n_page']}")
        name = f.name if len(f.name) <= 32 else f.name[:29] + "..."
        print(f"{name:<34} {page_label:>5} {s['chars']:8d} {pct('ones'):>8} "
              f"{pct('scaled'):>8} {pct('colored'):>8} {s['fonts']:5d}")
        for k in tot:
            tot[k] += s[k]

    if len(files) > 1 and tot["chars"]:
        n = tot["chars"]
        print("-" * len(head))
        print(f"{'TOTAL':<34} {'':>5} {n:8d} {100.0 * tot['ones'] / n:7.1f}% "
              f"{100.0 * tot['scaled'] / n:7.1f}% {100.0 * tot['colored'] / n:7.1f}%")

    print("\nfs=1.0   = characters whose FPDFText_GetFontSize is exactly 1.0")
    print("scaled   = characters whose matrix changes the size (|scale-1| > 0.01)")
    print("colored  = characters whose fill color is not black")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
