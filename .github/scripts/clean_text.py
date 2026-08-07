#!/usr/bin/env python3
"""Clean up text before sending it to edge-tts.

Edge's TTS service reads some characters out loud (markdown markers such as
``*`` / ``#``, decorative symbols, emoji, em dashes, ...). This script strips
those, while keeping the punctuation that only shapes prosody / pauses
(``. , ! ? ; :`` and their CJK counterparts).

Usage:
    python clean_text.py --in raw.txt --out text.txt
    cat raw.txt | python clean_text.py            # stdin -> stdout
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata

# Punctuation we keep: it is not spoken, it only creates pauses/intonation.
KEEP_PUNCT = ".,!?;:'\u3002\uff0c\u3001\uff01\uff1f\uff1b\uff1a()\uff08\uff09\u2026"

# Markdown / decorative characters that are read out loud. Dropped entirely.
DROP_CHARS = "*#`|\\<>{}[]^~\u3010\u3011\u300a\u300b\u3008\u3009\u300c\u300d\u300e\u300f\u3014\u3015\uff1c\uff1e\uff03\uff0a"

# Quotes: usually silent, but noisy in SSML and sometimes spoken. Dropped.
QUOTE_CHARS = "\"\u201c\u201d\u201e\u201f\u2018\u2019\u00ab\u00bb\u300c\u300d"

# Every dash-like character (incl. Chinese \u7834\u6298\u53f7 \u2014\u2014).
DASHES = "-\u2010\u2011\u2012\u2013\u2014\u2015\u2500\uff0d\u2043"

# CJK range used to decide whether to insert a Chinese or Western comma.
_CJK = re.compile(r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

_ARROWS = re.compile(r"[\u2190-\u21ff\u27f0-\u27ff\u2900-\u297f\u2b00-\u2bff]")
_URL = re.compile(r"<?(?:https?://|www\.)[^\s<>()\[\]\u3002\uff0c]+>?", re.IGNORECASE)
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_CODE_FENCE = re.compile(r"^\s*(?:```|~~~).*$", re.MULTILINE)
_LINE_MARKER = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]+|>+[ \t]*|[-*+\u2022\u00b7\u25cf\u25cb\u25a0\u25aa\u203b][ \t]+)"
)
_TABLE_SEP = re.compile(r"^[ \t]*\|?[ \t]*:?-{2,}:?[ \t]*(?:\|[ \t]*:?-{2,}:?[ \t]*)*\|?[ \t]*$")
_DUP_PUNCT = re.compile(r"([.,!?;:\u3002\uff0c\u3001\uff01\uff1f\uff1b\uff1a])(?:[ \t]*\1)+")
_SPACES = re.compile(r"[ \t\u00a0\u3000]+")
_BLANK_LINES = re.compile(r"\n{2,}")
# Characters that survived but carry no speech value at the edge of a line.
_EDGE_PUNCT = re.compile(r"^[\s.,;:!?\u3002\uff0c\u3001\uff1b\uff1a]+|[\s,;:\u3001\uff0c\uff1b\uff1a]+$")


def _comma_for(text: str) -> str:
    """Use a full-width comma for CJK text so the pause sounds natural."""
    return "\uff0c" if _CJK.search(text) else ", "


def _strip_symbols(text: str) -> str:
    """Drop emoji, pictographs, modifier symbols and invisible formatting chars."""
    out = []
    for ch in text:
        cat = unicodedata.category(ch)
        # So: emoji/pictographs/arrows/stars, Sk: modifier symbols,
        # Cf/Co/Cs: zero-width joiners, variation selectors, private use.
        if cat in ("So", "Sk", "Cf", "Co", "Cs"):
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def clean(text: str, *, drop_urls: bool = True) -> str:
    comma = _comma_for(text)

    # 1. markdown structures
    text = _CODE_FENCE.sub("", text)
    text = _MD_IMAGE.sub(" ", text)
    text = _MD_LINK.sub(r"\1", text)
    if drop_urls:
        text = _URL.sub(" ", text)

    # 2. line-level markers: headings, quotes, bullets, table separators
    lines = []
    for line in text.split("\n"):
        if _TABLE_SEP.match(line):
            continue
        lines.append(_LINE_MARKER.sub("", line))
    text = "\n".join(lines)

    # 3. dashes -> pause. Keep the hyphen inside words like "well-known".
    text = re.sub(rf"[{DASHES}]{{2,}}", comma, text)
    text = re.sub(rf"(?<=[ \t])[{DASHES}](?=[ \t])", comma, text)
    text = re.sub(rf"[\u2013\u2014\u2015\uff0d\u2500]", comma, text)

    # 4. emoji / pictographs / invisible chars, then arrows (category Sm/So)
    text = _strip_symbols(text)
    text = _ARROWS.sub(" ", text)

    # 5. leftover markdown & decorative characters
    text = text.translate({ord(c): " " for c in DROP_CHARS})
    text = text.translate({ord(c): None for c in QUOTE_CHARS})
    # underscore -> space so snake_case stays two words instead of "underscore"
    text = text.replace("_", " ")

    # 6. tidy up punctuation and whitespace
    text = _DUP_PUNCT.sub(r"\1", text)
    text = _SPACES.sub(" ", text)
    text = _BLANK_LINES.sub("\n", text)
    text = "\n".join(
        stripped
        for line in text.split("\n")
        if (stripped := _EDGE_PUNCT.sub("", line).strip())
    )
    # drop space before punctuation left behind by removals ("word ." -> "word.")
    text = re.sub(r" +([.,!?;:\u3002\uff0c\u3001\uff01\uff1f\uff1b\uff1a])", r"\1", text)
    return text.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-i", "--in", dest="infile", help="input file (default: stdin)")
    parser.add_argument("-o", "--out", dest="outfile", help="output file (default: stdout)")
    parser.add_argument(
        "--keep-urls", action="store_true", help="do not remove URLs from the text"
    )
    args = parser.parse_args()

    raw = (
        open(args.infile, encoding="utf-8").read()
        if args.infile
        else sys.stdin.read()
    )
    result = clean(raw, drop_urls=not args.keep_urls)

    if not result:
        print("clean_text: nothing left to speak after filtering.", file=sys.stderr)
        return 1

    if args.outfile:
        with open(args.outfile, "w", encoding="utf-8") as fobj:
            fobj.write(result)
    else:
        sys.stdout.write(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
