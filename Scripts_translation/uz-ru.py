#!/usr/bin/env python3
"""
clean_merge_uzru.py - clean, normalize, merge and de-duplicate the uz-ru parallel corpus (JSONL, UTF-8).

Record format (input and output):
    {"pair": "uz-ru" | "ru-uz", "source": "...", "target": "..."}
Extra fields such as "origin" are dropped.

USAGE
  1) Merge dataset folders split by split (train/dev/test), recommended:
       python clean_merge_uzru.py uz-ru-1.3M uz-ru-1.2M -o merged_out
     -> merged_out/train.jsonl, dev.jsonl, test.jsonl, stats.json
     Rows that also appear in dev/test are removed from train (no leakage).

  2) Merge arbitrary JSONL files into a single file:
       python clean_merge_uzru.py a.jsonl b.jsonl -o merged.jsonl

WHAT IT DOES (per source/target text)
  - repairs UTF-8 (BOM, lone surrogates), Unicode NFC normalization
  - decodes HTML entities, including broken ones like "&amp; apos ;" -> '   and "&amp; quot;" -> "
  - strips HTML tags, control characters, zero-width/soft-hyphen characters
  - ALL apostrophe variants (' ‘ ’ ʻ ʼ ʹ ʽ ` ´ ′ ...) -> plain '
  - NBSP / tabs / multiple spaces -> single space, trims both ends
  - de-tokenizes "tokenized" text:  "o ‘ zbek , ta ’ lim ." -> "o'zbek, ta'lim."
    and fixes spacing around brackets and quotes (« text » -> «text», “ text ” -> “text”)
  - removes layout junk: leading bullets (•), runs of * or ~, "-----", "....." etc.
  - drops rows: bad JSON / missing fields, empty side, no letters at all,
    identical source/target, wrong script (uz side must be Latin, ru side Cyrillic)
  - removes exact duplicates (per direction) across ALL input files
Speed: use --workers N (default = number of CPU cores). RAM: ~100 bytes per unique row.
"""
import argparse
import hashlib
import html
import json
import multiprocessing as mp
import os
import re
import sys
import time
import unicodedata
from collections import Counter
from itertools import islice
from pathlib import Path

# ----------------------------------------------------------------------------
# Character tables
# ----------------------------------------------------------------------------
APOSTROPHES = "\u2019\u2018\u201b\u02bc\u02bb\u02b9\u02bd\u0060\u00b4\u2032\uff07\u055a\u02c8\u02ca"
SPACES = ("\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
          "\u202f\u205f\u3000\u2028\u2029\t\r\n\x0b\x0c")
INVISIBLE = "\u200b\u200c\u200d\u2060\ufeff\u00ad\u200e\u200f"
TRANS = {}
for _c in APOSTROPHES:
    TRANS[ord(_c)] = "'"
for _c in SPACES:
    TRANS[ord(_c)] = " "
for _c in INVISIBLE:
    TRANS[ord(_c)] = None

ASCII_QUOTES_TRANS = {ord(c): '"' for c in "\u201c\u201d\u201e\u201f\u00ab\u00bb\u2033\uff02"}

# ----------------------------------------------------------------------------
# Regexes
# ----------------------------------------------------------------------------
# Entities, also broken ones: "&amp; apos ;", "&amp;amp; quot;", "&amp; # 91;"
ENT_RE = re.compile(r"&\s*(?:amp\s*;\s*)*(apos|quot|lt|gt|nbsp|amp|#\s*\d{1,6}|#x[0-9a-fA-F]{1,6})\s*;", re.I)
ENT_MAP = {"apos": "'", "quot": '"', "lt": "<", "gt": ">", "nbsp": " ", "amp": "&"}
TAG_RE = re.compile(r"</?[A-Za-z][^<>]{0,200}>")
CONTROL_RE = re.compile(r"[\x00-\x08\x0e-\x1f\x7f-\x9f]")
WS_RE = re.compile(r"\s+")

TILDE_RE = re.compile(r"(?:~\s*){2,}")
LEAD_BULLET_RE = re.compile(r"^(?:[\u2022\u00b7\u25aa\u25a0\u25cf\u25e6\u25ab\u25ba\u25c6\u2023]\s*)+")
LEAD_STAR_RE = re.compile(r"^(?:[*&]\s+|\*+\s*)+")
TRAIL_STAR_RE = re.compile(r"(?:\s*\*)+$")
DOTS_RE = re.compile(r"\.{4,}")
REPEAT_PUNCT_RE = re.compile(r"([!?,;:\-_*=#])\1{2,}")

# "tokenized" detection (after apostrophes are normalized to ')
TOK_RE = re.compile(r"\S [,.;:!?)\]}](?:\s|$)|[(\[{] \S|[^\W\d_] ' [^\W\d_]")
APOS_JOIN_RE = re.compile(r"(?<=[^\W\d_]) ' (?=[^\W\d_])")
SPACE_BEFORE_RE = re.compile(r"(?<=[^\s.])\s+([,.;!?)\]}])")
COLON_BEFORE_RE = re.compile(r"(?<!\d)\s+:")           # "word :" -> "word:" (keeps "10 : 30")
SPACE_AFTER_OPEN_RE = re.compile(r"([(\[{])\s+")
OPEN_QUOTES_RE = re.compile(r"([\u201c\u00ab\u201e])\s+")
CLOSE_QUOTES_RE = re.compile(r"\s+([\u201d\u00bb])")

LETTER_RE = re.compile(r"[^\W\d_]")
LATIN_RE = re.compile(r"[A-Za-z\u00c0-\u024f]")
CYR_RE = re.compile(r"[\u0400-\u04ff]")
URL_RE = re.compile(r"(?:https?://|www\.)\S+|\b[\w.+-]+@[\w-]+\.[\w.-]+", re.I)

OPTS = None


def _ent_sub(m):
    key = m.group(1).lower().replace(" ", "")
    if key in ENT_MAP:
        return ENT_MAP[key]
    try:
        cp = int(key[2:], 16) if key.startswith("#x") else int(key[1:])
        return chr(cp)
    except (ValueError, OverflowError):
        return " "


def _fix_ascii_quotes(s: str) -> str:
    """Tokenized text puts spaces inside quotes: ' " word " ' -> ' "word" '."""
    if s.count('"') < 2 or s.count('"') % 2:
        return s
    out, opening, i = [], True, 0
    parts = s.split('"')
    # parts[0] " parts[1] " parts[2] ...
    res = parts[0]
    for idx in range(1, len(parts)):
        seg = parts[idx]
        if opening:                       # opening quote: no space after it
            res = res + '"' + seg.lstrip(" ")
        else:                             # closing quote: no space before it
            res = res.rstrip(" ") + '"' + seg
        opening = not opening
    return res


def clean_text(s: str) -> str:
    s = s.encode("utf-8", "ignore").decode("utf-8")           # drop lone surrogates
    if "&" in s:
        s = ENT_RE.sub(_ent_sub, s)
        s = html.unescape(s)
    if "<" in s:
        s = TAG_RE.sub(" ", s)
    s = unicodedata.normalize("NFC", s)
    s = s.translate(TRANS)
    s = CONTROL_RE.sub("", s)

    # layout junk
    s = TILDE_RE.sub(" ", s)
    s = LEAD_BULLET_RE.sub("", s)
    s = LEAD_STAR_RE.sub("", s)
    s = TRAIL_STAR_RE.sub("", s)
    s = DOTS_RE.sub("...", s)
    s = REPEAT_PUNCT_RE.sub(r"\1", s)
    s = WS_RE.sub(" ", s).strip()

    # de-tokenize
    mode = OPTS.detok
    if mode != "off" and (mode == "always" or TOK_RE.search(s)):
        s = APOS_JOIN_RE.sub("'", s)
        s = SPACE_BEFORE_RE.sub(r"\1", s)
        s = COLON_BEFORE_RE.sub(":", s)
        s = SPACE_AFTER_OPEN_RE.sub(r"\1", s)
    s = OPEN_QUOTES_RE.sub(r"\1", s)
    s = CLOSE_QUOTES_RE.sub(r"\1", s)
    s = _fix_ascii_quotes(s)

    if OPTS.ascii_quotes:
        s = s.translate(ASCII_QUOTES_TRANS)
    return WS_RE.sub(" ", s).strip()


def _h64(text: str) -> int:
    return int.from_bytes(hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest(), "big")


def process_line(line: str):
    """-> (status, pair, src, tgt, key_directional, key_agnostic). status == 'ok' or a drop reason."""
    line = line.strip()
    if not line:
        return ("blank", None, None, None, 0, 0)
    try:
        d = json.loads(line)
        pair, src, tgt = d["pair"], d["source"], d["target"]
        if pair not in ("uz-ru", "ru-uz") or not isinstance(src, str) or not isinstance(tgt, str):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        return ("bad_record", None, None, None, 0, 0)

    src, tgt = clean_text(src), clean_text(tgt)
    if not src or not tgt:
        return ("empty", None, None, None, 0, 0)
    if not LETTER_RE.search(src) or not LETTER_RE.search(tgt):
        return ("no_letters", None, None, None, 0, 0)
    if src.casefold() == tgt.casefold():
        return ("identical_sides", None, None, None, 0, 0)

    uz, ru = (src, tgt) if pair == "uz-ru" else (tgt, src)
    if OPTS.script_check:
        n_lat, n_cyr = len(LATIN_RE.findall(uz)), len(CYR_RE.findall(uz))
        if n_lat < n_cyr:
            return ("uz_side_wrong_script", None, None, None, 0, 0)
        n_lat, n_cyr = len(LATIN_RE.findall(ru)), len(CYR_RE.findall(ru))
        if n_cyr < n_lat:
            return ("ru_side_wrong_script", None, None, None, 0, 0)
    if OPTS.drop_urls and (URL_RE.search(src) or URL_RE.search(tgt)):
        return ("contains_url", None, None, None, 0, 0)

    k_dir = _h64(pair + "\x00" + src + "\x00" + tgt)
    k_agn = _h64(uz + "\x00" + ru)
    return ("ok", pair, src, tgt, k_dir, k_agn)


def process_chunk(lines):
    return [process_line(l) for l in lines]


def _init_worker(opts):
    global OPTS
    OPTS = opts


# ----------------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------------
def iter_chunks(paths, size=20000):
    for p in paths:
        with open(p, "r", encoding="utf-8-sig", errors="replace", newline="") as f:
            while True:
                chunk = list(islice(f, size))
                if not chunk:
                    break
                yield chunk


def run_job(paths, out_path, pool, held_out=None, collect_keys=None, label=""):
    """Process files in `paths` -> out_path. Returns Counter of stats."""
    stats = Counter()
    seen = set()
    chunks = iter_chunks(paths)
    results = pool.imap(process_chunk, chunks) if pool else map(process_chunk, chunks)
    t0 = time.time()
    with open(out_path, "w", encoding="utf-8", newline="\n") as out:
        for batch in results:
            for status, pair, src, tgt, k_dir, k_agn in batch:
                if status == "blank":
                    continue
                stats["read"] += 1
                if status != "ok":
                    stats["dropped_" + status] += 1
                    continue
                if held_out is not None and k_agn in held_out:
                    stats["dropped_also_in_dev_or_test"] += 1
                    continue
                if k_dir in seen:
                    stats["dropped_duplicate"] += 1
                    continue
                seen.add(k_dir)
                if collect_keys is not None:
                    collect_keys.add(k_agn)
                out.write(json.dumps({"pair": pair, "source": src, "target": tgt},
                                     ensure_ascii=False, separators=(",", ":")) + "\n")
                stats["written"] += 1
            if stats["read"] % 200000 < 20000:
                print(f"  [{label}] {stats['read']:>9,} read | {stats['written']:>9,} kept | "
                      f"{time.time() - t0:5.0f}s", file=sys.stderr, flush=True)
    return stats


def main():
    global OPTS
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", type=Path,
                    help="dataset folders (each with train/dev/test.jsonl) OR plain .jsonl files")
    ap.add_argument("-o", "--output", type=Path, required=True,
                    help="output folder (folder mode) or output .jsonl file (file mode)")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--detok", choices=["auto", "always", "off"], default="auto",
                    help="remove tokenizer spaces around punctuation (default: auto-detect per text)")
    ap.add_argument("--ascii-quotes", action="store_true", help="convert “ ” „ « » to plain \"")
    ap.add_argument("--no-script-check", dest="script_check", action="store_false",
                    help="do not require Latin for uz side / Cyrillic for ru side")
    ap.add_argument("--drop-urls", action="store_true", help="drop rows containing URLs / e-mails")
    OPTS = ap.parse_args()

    folder_mode = all(p.is_dir() for p in OPTS.inputs)
    if not folder_mode and any(p.is_dir() for p in OPTS.inputs):
        ap.error("give either only folders or only files")

    pool = None
    if OPTS.workers > 1:
        pool = mp.Pool(OPTS.workers, initializer=_init_worker, initargs=(OPTS,))

    all_stats = {}
    t0 = time.time()
    if folder_mode:
        OPTS.output.mkdir(parents=True, exist_ok=True)
        held_out = set()
        for split in ("test", "dev", "train"):      # test first: it has priority over dev, dev over train
            paths = [d / f"{split}.jsonl" for d in OPTS.inputs if (d / f"{split}.jsonl").exists()]
            if not paths:
                continue
            print(f"== {split}: " + ", ".join(str(p) for p in paths), file=sys.stderr)
            keys = set()
            st = run_job(paths, OPTS.output / f"{split}.jsonl", pool,
                         held_out=held_out if split != "test" else None,
                         collect_keys=keys if split != "train" else None, label=split)
            held_out |= keys
            all_stats[split] = dict(st)
        (OPTS.output / "stats.json").write_text(json.dumps(all_stats, indent=2), encoding="utf-8")
    else:
        OPTS.output.parent.mkdir(parents=True, exist_ok=True)
        st = run_job(OPTS.inputs, OPTS.output, pool, label="merge")
        all_stats["merged"] = dict(st)

    if pool:
        pool.close()
        pool.join()

    print(f"\nDone in {time.time() - t0:.0f}s", file=sys.stderr)
    for name, st in all_stats.items():
        print(f"[{name}]", file=sys.stderr)
        for k, v in sorted(st.items(), key=lambda kv: -kv[1]):
            print(f"   {k:<32}{v:>12,}", file=sys.stderr)


if __name__ == "__main__":
    main()