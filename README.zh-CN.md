# pdfium-font-metrics

[English](README.md) | **中文**

> Character-level font dimensions that `pypdfium2` does not expose: real font size, weight,
> italic flag, fill colour — and the text matrix that decides what "real size" means.

一个单文件模块，把 pdfium 里一直存在、但 `pypdfium2` 高层 API 没封装的五个函数接出来。
核心是那个**文本矩阵**：

```python
# 这两行在 PDF 里是等价的，都画 12pt 的字
/F1 12 Tf  1 0 0 1 60 760 Tm  (hello) Tj     # 直接写字号
/F1  1 Tf 12 0 0 12 60 760 Tm (hello) Tj     # 写 1.0，缩放交给矩阵

# 但 FPDFText_GetFontSize 对第二种只返回 1.0
```

大量真实文档用的是第二种。只读字号、不读矩阵，拿到的就是 `1.0`。

---

## 1. 问题有多普遍

`bench.py` 在 6 份真实 PDF 上的统计（每份取前 6 页）：

| 文件 | 页 | 字符 | `fs=1.0` | 矩阵改字号 | 非黑 | 字体数 |
|---|---|---:|---:|---:|---:|---:|
| `irs-f1040.pdf`（美国税表，Acrobat 表单） | 2 | 7 927 | **100.0%** | 100.0% | 0.2% | 9 |
| `eu-gdpr-de.pdf`（EU 官方排版，88 页） | 6 | 28 211 | **100.0%** | 100.0% | 0.0% | 3 |
| `rfc9110-http-semantics.pdf`（IETF） | 6 | 5 447 | **100.0%** | 100.0% | 93.8% | 4 |
| `arxiv-attention-1706.03762.pdf`（LaTeX） | 6 | 15 340 | 0.0% | 13.9% | 1.2% | 20 |
| `cn-xiaokang-zh.pdf` | 6 | 4 793 | 0.0% | 0.0% | 100.0% | 1 |
| `us-patent-3987654.pdf`（扫描件，无文字层） | 6 | 0 | — | — | — | 0 |
| **合计** | | **61 718** | **67.4%** | 70.8% | 16.4% | |

**4 份有文字层的文档里，3 份是 100%**。LaTeX 那篇最规矩（直接写实际字号），
但仍有 13.9% 的字符字号被矩阵改变过。

## 2. 为什么现成工具拿不到

拿 `pdftext`（[datalab-to/pdftext](https://github.com/datalab-to/pdftext)，Apache-2.0，
Apache 生态里最常用的 pypdfium2 封装）举例。它的字符提取只调这三个：

```python
# pdftext/pdf/chars.py
get_unicode     = pdfium_c.FPDFText_GetUnicode
get_char_angle  = pdfium_c.FPDFText_GetCharAngle
get_fontsize    = pdfium_c.FPDFText_GetFontSize      # ← 原值，没乘矩阵
get_fontweight  = pdfium_c.FPDFText_GetFontWeight
```

整个包里**没有 `FPDFText_GetMatrix`，也没有 `FPDFText_GetFillColor`**（`grep -r` 可验）。
所以它对上面那三份文档给出的字号是：

```
pdftext 眼中的 irs-f1040.pdf p0（1109 个 span）
   size=1.000  weight=-1   name=（空）                     ×542
   size=1.000  weight=400  name=HelveticaNeueLTStd-Roman   ×459
   size=1.000  weight=700  name=HelveticaNeueLTStd-Bd      ×96

pdftext 眼中的 eu-gdpr-de.pdf p0 → 全部 size=1.000
pdftext 眼中的 rfc9110.pdf     p0 → 全部 size=1.000
```

`weight` 那一列也值得看一眼：`440` / `804` / `425` / `-1`。那是 PDF 字体描述符里的
stemV 系粗值，**不是 CSS 字重**。本模块会按字体名归一化到 `400` / `700`。

> 这不是说 pdftext 不好。它的目标是把 PDF 变成 blocks/lines/spans 的文本结构，
> 字号只是顺带输出。做纯文本提取它够用；做**版式重建**（把字按原大小画回去）就不够。

## 3. 用法

```python
from pdfium_font import PageText

with PageText("doc.pdf", page_index=0) as pt:
    for ch in pt.chars():
        # ch.size 已经是设备空间字号
        print(ch.text, ch.size, ch.font, ch.weight, ch.italic, ch.color)

    # 按 run 聚合：同字体 / 同字号 / 同字重 / 同色
    for r in pt.runs():
        print(r["size"], r["raw_size"], r["scale"], r["font"], r["text"])
```

`CharFont` 字段：

| 字段 | 含义 |
|---|---|
| `size` | **设备空间字号**（pt），`raw_size * scale`。你要用的就是这个 |
| `raw_size` | `FPDFText_GetFontSize` 原值，诊断用 |
| `scale` | 从矩阵推出的缩放因子 |
| `matrix` | 字符有效变换矩阵 `(a, b, c, d, e, f)` |
| `size_h` / `size_v` | 水平 / 垂直等效字号。非等比缩放时两者不等，分别影响字宽与行高 |
| `font` | 字体名，已剥掉 `ABCDEF+` 六位子集前缀 |
| `weight` | 归一化到 100–900 的字重 |
| `italic` | flags 里的 Italic 位，或字体名含 italic/oblique |
| `color` | 填充色 `(r, g, b, a)` |
| `bbox` | 紧贴字形的字符框 |
| `loose` | 按 advance 算的字符框，更接近排版占位 |
| `origin` | 字符原点（基线起点），行聚类用 |

不需要 `pikepdf`、不需要 `pymupdf`、不需要重编译 pdfium。唯一依赖是 `pypdfium2`。

## 4. 怎么验

```bash
pip install pypdfium2

python make_sample.py      # 生成 examples/one-pt-tf.pdf（零依赖手写字节）
python demo.py             # 看 1.0 Tf 被还原成 12pt 的过程
python bench.py your.pdf   # 统计你的 PDF 里有多少字符依赖矩阵
```

`make_sample.py` 生成的样本里六行分别是：矩阵缩放 / 直接字号 / 矩阵+颜色 /
粗体 / 斜体 / 衬线，用来确认六个维度都读对了：

```
one character, in full:
  text      = 'A'
  raw_size  = 1.000        <- FPDFText_GetFontSize only gives you this
  matrix    = [12.000 0.000 0.000 12.000 60.000 760.000]
  scale     = sqrt(|a|*|d|) = 12.000
  size      = raw_size * scale = 12.000   <- the real font size
```

## 5. 和 PyMuPDF 对不齐的那 0.1% 不是 bug

用 PyMuPDF 的 `span["size"]` 当基准（容差 0.02pt）跑整页：

| 文件 | 字符 | 一致率 |
|---|---:|---:|
| `rfc9110` | 5 447 | 100.00% |
| `arxiv-attention` | 15 340 | 100.00% |
| `eu-gdpr-de` | 28 211 | 99.91% |
| `irs-f1040` | 7 927 | 99.65% |

两个偏差样本，逐个查过：

| 字符 | 本模块 | PyMuPDF | PDF 里的矩阵 | bbox 高 ÷ 字号 |
|---|---:|---:|---|---|
| IRS p0 `U` | 12.00 | 20.00 | `a = d = 12.0`, `raw = 1.0` | 8.3 / 12 = **0.69** ✔ |
| GDPR p0 `D` | 8.53 | 9.60 | `a = d = 8.529`, `raw = 1.0` | 5.70 / 8.53 = **0.67** ✔ |

矩阵里明写着 `1.0 Tf` + `a = d = 12.0`，设备空间字号就是 12——这是定义，不是估计。
bbox 高度除以字号得 0.69 / 0.67，正好是大写字母的标准 cap height 比例；
按 PyMuPDF 给的 20 和 9.6 去算会掉到 0.41 和 0.59，反而对不上。

原因：**PyMuPDF 的 `span["size"]` 是 span 级聚合值，本模块是字符级**。
GDPR 那个 span 有 85 个字符，9.6 恰好是整份文档的正文号——它把一个 span 里混排的
字号统一了。

## 6. 这是什么，不是什么

- **是**：一个字符级字体属性提取器。给你 `字符 + 坐标 + 字号 + 字重 + 斜体 + 颜色`。
- **不是**文本提取库。它不产出行/段/栏，不做阅读顺序，不做表格。那是 `pdftext`、
  `pymupdf`、`pdfplumber` 的活。
- **不是** PDF 重排/重建引擎。它只负责把"这段字原本多大、多粗、什么颜色"说准，
  怎么画回去是你的事。

已知边界：

- 纯旋转矩阵（`a = d = 0`）走 `sqrt(|det|)` 分支。这条逻辑是数学上必需的，
  但在 1 197 页语料里没有命中过旋转字符，**未经过真实语料验证**。
- `Ts`（Text Rise，上下标位移）取不到：pdfium 不暴露，`FPDFText_GetCharOrigin`
  已经把它折进 origin 了。
- 只处理文字层。扫描件没有文字层，`count()` 直接是 0。

## 7. 许可

MIT。`pypdfium2` 是 Apache-2.0 / BSD-3-Clause，pdfium 本体是 BSD-3-Clause。

## 8. 联系

纠错、提问、想讨论 PDF 重建里别的坑：`contact@digitrail.net`，或直接开 Issue。

这个库是从 [Digitrail](https://digitrail.net)（PDF 版式重建工具）里剥出来的一小块。
它只承担一件事——把 pdfium 没封装清楚的字体维度说清楚——不承载任何产品逻辑，所以单独开源。
