"""
Convert an English-Uzbek CSV/TSV into the training JSONL format (both directions):

    {"pair": "en-uz", "source": "<english>", "target": "<uzbek>", "origin": "eng_uz"}
    {"pair": "uz-en", "source": "<uzbek>", "target": "<english>", "origin": "eng_uz"}

Input columns (tab- or comma-separated, detected automatically):
    sentence_id  source_lang  source_texts  translation  references  confidence_score  agglutination_index

  source_texts -> English side
  references   -> Uzbek side (default; falls back to "translation" when references is empty)

Default: 1,500,000 sentence pairs x 2 directions = 3,000,000 lines in train.jsonl,
plus dev.jsonl / test.jsonl (2,000 pairs each, x2 directions) from rows NOT used for train.

Usage:
  python csv_to_jsonl.py data.csv
  python csv_to_jsonl.py data.csv --out-dir /data/datasets/ttt/en-uz
  python csv_to_jsonl.py data.csv --rows 1500000 --dev 2000 --test 2000
  python csv_to_jsonl.py data.csv --target-col translation        # use the "translation" column instead
  python csv_to_jsonl.py data.csv --min-score 0.75                # keep only confidence_score >= 0.75
  python csv_to_jsonl.py data.csv --shuffle                       # random 1.5M instead of the first 1.5M
"""

import argparse
import csv
import json
import random
import re
import sys
import time
from pathlib import Path

csv.field_size_limit(sys.maxsize)

# Uzbek apostrophe variants -> plain ' (same style as the TIL uz-ru data: o'zbek, g'alaba, ta'lim)
APOSTROPHES = re.compile(r"[ʻʼ‘’`´ʹ]")
SPACES = re.compile(r"\s+")
LANG = {"eng": "en", "en": "en", "english": "en", "uzb": "uz", "uz": "uz", "rus": "ru", "ru": "ru"}


def clean(text, uzbek=False, normalize_apostrophes=True):
    text = SPACES.sub(" ", (text or "").replace("﻿", "")).strip()
    if uzbek and normalize_apostrophes:
        text = APOSTROPHES.sub("'", text)
    # "hikoyasi ." -> "hikoyasi."
    text = re.sub(r"\s+([.,!?;:])", r"\1", text)
    return text


def detect_delimiter(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        first = f.readline()
    return "\t" if first.count("\t") >= first.count(",") else ","


def main():
    ap = argparse.ArgumentParser(description="English-Uzbek CSV -> bidirectional training JSONL")
    ap.add_argument("csv", help="input file, e.g. data.csv")
    ap.add_argument("--out-dir", default=".", help="where train/dev/test.jsonl are written (default: current folder)")
    ap.add_argument("--rows", type=int, default=1_500_000, help="sentence pairs for train (each -> 2 lines)")
    ap.add_argument("--dev", type=int, default=2000, help="sentence pairs for dev.jsonl (0 = none)")
    ap.add_argument("--test", type=int, default=2000, help="sentence pairs for test.jsonl (0 = none)")
    ap.add_argument("--source-col", default="source_texts")
    ap.add_argument("--target-col", default="references", help="Uzbek column: references | translation")
    ap.add_argument("--fallback-col", default="translation", help="used when target-col is empty ('' = off)")
    ap.add_argument("--min-score", type=float, default=None, help="minimum confidence_score (default: keep all)")
    ap.add_argument("--src-lang", default="en", help="language of source_texts (default en)")
    ap.add_argument("--tgt-lang", default="uz")
    ap.add_argument("--origin", default="eng_uz", help='value of the "origin" field')
    ap.add_argument("--keep-apostrophes", action="store_true", help="don't convert ʻ ʼ ‘ ’ to ' in Uzbek")
    ap.add_argument("--max-chars", type=int, default=1000, help="skip pairs longer than this (either side)")
    ap.add_argument("--shuffle", action="store_true", help="random selection instead of the first N rows")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    path = Path(args.csv)
    if not path.exists():
        sys.exit(f"File not found: {path}")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    delim = detect_delimiter(path)
    print(f"Reading {path}  (delimiter: {'TAB' if delim == chr(9) else 'comma'})")

    need = args.rows + args.dev + args.test
    stats = {"rows": 0, "empty": 0, "low_score": 0, "too_long": 0, "same_text": 0, "duplicate": 0,
             "used_fallback": 0}
    pairs, seen = [], set()
    t0 = time.time()
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=delim)
        cols = reader.fieldnames or []
        for c in (args.source_col, args.target_col):
            if c not in cols:
                sys.exit(f"Column '{c}' not found. Columns are: {cols}")
        for row in reader:
            stats["rows"] += 1
            src = clean(row.get(args.source_col))
            tgt = clean(row.get(args.target_col), uzbek=True, normalize_apostrophes=not args.keep_apostrophes)
            if not tgt and args.fallback_col and row.get(args.fallback_col):
                tgt = clean(row.get(args.fallback_col), uzbek=True, normalize_apostrophes=not args.keep_apostrophes)
                stats["used_fallback"] += 1
            if not src or not tgt:
                stats["empty"] += 1
                continue
            if args.min_score is not None:
                try:
                    if float(row.get("confidence_score") or 0) < args.min_score:
                        stats["low_score"] += 1
                        continue
                except ValueError:
                    pass
            if len(src) > args.max_chars or len(tgt) > args.max_chars:
                stats["too_long"] += 1
                continue
            if src.lower() == tgt.lower():
                stats["same_text"] += 1
                continue
            key = src.lower()
            if key in seen:
                stats["duplicate"] += 1
                continue
            seen.add(key)
            pairs.append((src, tgt))
            if not args.shuffle and len(pairs) >= need:
                break
            if stats["rows"] % 500_000 == 0:
                print(f"  read {stats['rows']:,} rows, kept {len(pairs):,}  ({time.time() - t0:.0f}s)")

    if args.shuffle:
        random.Random(args.seed).shuffle(pairs)
    if len(pairs) < need:
        print(f"  WARNING: only {len(pairs):,} usable pairs, wanted {need:,} "
              f"({args.rows:,} train + {args.dev:,} dev + {args.test:,} test)")
        # keep dev/test, shrink train
        n_eval = min(args.dev + args.test, len(pairs) // 10)
        dev_n = min(args.dev, n_eval // 2) if args.dev else 0
        test_n = min(args.test, n_eval - dev_n) if args.test else 0
    else:
        dev_n, test_n = args.dev, args.test

    # train = first N, dev/test = the rows after them (never overlap)
    train = pairs[: len(pairs) - dev_n - test_n][: args.rows]
    dev = pairs[len(train): len(train) + dev_n]
    test = pairs[len(train) + dev_n: len(train) + dev_n + test_n]

    fwd, bwd = f"{args.src_lang}-{args.tgt_lang}", f"{args.tgt_lang}-{args.src_lang}"

    def write(name, rows):
        if not rows:
            return 0
        p = out_dir / name
        with open(p, "w", encoding="utf-8") as f:
            for s, t in rows:
                f.write(json.dumps({"pair": fwd, "source": s, "target": t, "origin": args.origin}, ensure_ascii=False) + "\n")
                f.write(json.dumps({"pair": bwd, "source": t, "target": s, "origin": args.origin}, ensure_ascii=False) + "\n")
        print(f"  {name:<12} {len(rows):>10,} pairs -> {2 * len(rows):>10,} lines  {p}")
        return 2 * len(rows)

    print("\nWriting:")
    total = write("train.jsonl", train) + write("dev.jsonl", dev) + write("test.jsonl", test)
    summary = {"input": str(path), "pairs": {fwd: len(train), "dev": len(dev), "test": len(test)},
               "lines_total": total, "filtered": stats, "target_column": args.target_col,
               "apostrophes_normalized": not args.keep_apostrophes}
    (out_dir / "stats.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    skipped = ", ".join(f"{k} {v:,}" for k, v in stats.items() if k not in ("rows", "used_fallback") and v)
    print(f"\nRead {stats['rows']:,} rows in {time.time() - t0:.0f}s. Skipped: {skipped or 'none'}")
    if stats["used_fallback"]:
        print(f"Used '{args.fallback_col}' for {stats['used_fallback']:,} rows with an empty '{args.target_col}'")
    if train:
        s, t = train[0]
        print(f"\nExample:\n  {fwd}: {s}\n     -> {t}")


if __name__ == "__main__":
    main()
