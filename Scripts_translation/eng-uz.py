
import argparse
import csv
import json
import os
import re
import sys
import unicodedata
from collections import Counter

# Windows'da C long 32-bit, sys.maxsize OverflowError beradi
csv.field_size_limit(2**31 - 1)

# --- Apostroflar: o' / g' / tutuq belgisi uchun 
apostrof = "ʻʼ‘’`´ʹ′‛"
apostrof_jadval = str.maketrans({ch: "'" for ch in apostrof})

# --- Ko'rinmas belgilar ---
boshliq = re.compile("[​‍⁠﻿­]")
# NBSP, tor bo'shliq, tab va h.k. -> oddiy bo'shliq
SPACES_RE = re.compile(r"[\s    ]+")

# --- Sonlar ---
# "3 . 5" / "3. 5" / "3 .5" -> "3.5",  "1 , 5" -> "1,5"
# (lekin "April 1, 2004" o'zgarmaydi: vergul oldida bo'shliq yo'q, keyin esa bor)
NUM_SPLIT_DOT_RE = re.compile(r"(\d)\s*\.\s*(?=\d)")
NUM_SPLIT_COMMA_RE = re.compile(r"(\d)\s+,\s*(?=\d)")
# "25 %" -> "25%"
PERCENT_RE = re.compile(r"(\d)\s+%")

# --- Tinish belgilari ---
SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([.,!?;:)\]}»])")
SPACE_AFTER_OPEN_RE = re.compile(r"([(\[{«])\s+")
# Harfdan keyin vergul/nuqta-vergul yopishib qolgan bo'lsa bo'shliq qo'shish: "Index,Himalayan"
NO_SPACE_AFTER_RE = re.compile(r"(?<=[^\W\d_])([,;])(?=[^\W\d_])")


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = INVISIBLE_RE.sub("", text)
    text = text.translate(APOS_TABLE)
    text = SPACES_RE.sub(" ", text)
    text = NUM_SPLIT_DOT_RE.sub(r"\1.", text)
    text = NUM_SPLIT_COMMA_RE.sub(r"\1,", text)
    text = PERCENT_RE.sub(r"\1%", text)
    text = SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    text = SPACE_AFTER_OPEN_RE.sub(r"\1", text)
    text = NO_SPACE_AFTER_RE.sub(r"\1 ", text)
    text = SPACES_RE.sub(" ", text)
    return text.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", default="data.csv")
    ap.add_argument("-o", "--output", default="data.jsonl")
    ap.add_argument("--path", default=None,
                    help="'path' maydoni qiymati (default: kirish faylining nomi)")
    ap.add_argument("--keep-duplicates", action="store_true")
    args = ap.parse_args()

    path_value = args.path or os.path.basename(args.input)
    stats = Counter()
    seen = set()

    with open(args.input, encoding="utf-8", newline="") as fin, \
         open(args.output, "w", encoding="utf-8") as fout:
        reader = csv.DictReader(fin, delimiter="\t", quoting=csv.QUOTE_NONE)
        for row in reader:
            stats["read"] += 1
            src_raw = row.get("source_texts") or ""
            tgt_raw = row.get("translation") or ""

            src = clean_text(src_raw)
            tgt = clean_text(tgt_raw)

            if src != src_raw:
                stats["source_changed"] += 1
            if tgt != tgt_raw:
                stats["translation_changed"] += 1

            if not src or not tgt:
                stats["dropped_empty"] += 1
                continue

            if not args.keep_duplicates:
                key = (src, tgt)
                if key in seen:
                    stats["dropped_duplicate"] += 1
                    continue
                seen.add(key)

            record = {"source": src, "translation": tgt, "path": path_value}
            fout.write(json.dumps(record, ensure_ascii=False) + "\n")
            stats["written"] += 1

            if stats["read"] % 200_000 == 0:
                print(f"  {stats['read']:,} qator o'qildi...", flush=True)

    print("\nNatija:")
    for k in ("read", "source_changed", "translation_changed",
              "dropped_empty", "dropped_duplicate", "written"):
        print(f"  {k:20s} {stats[k]:>12,}")
    print(f"\nSaqlandi: {args.output}")


if __name__ == "__main__":
    main()



      