
# -*- coding: utf-8 -*-
"""
Shared cleaning code and pipeline for the eng-uzb / uzb-eng dataset formatters.
Input and output are always read/written as UTF-8.

Input columns used : source_lang, source_texts, translation
                     (optionally confidence_score for --min-confidence)
Output (JSONL)     : source_lang, source_texts, translation_lang, translation
"""
import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter

# Windows: a C long is 32-bit, so sys.maxsize would raise OverflowError
csv.field_size_limit(2**31 - 1)

# The ONE apostrophe used on the Uzbek side (oʻ, gʻ, tutuq belgisi).
# U+0027 (ASCII). Change to "\u02bb" if you prefer the okina.
APOSTROPHE = "'"

# ======================================================================
# Invisible / control characters, whitespace
# ======================================================================
# zero-width space / non-joiner / joiner, word joiner, BOM, soft hyphen
korinmas_re = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u00ad]")
# C0/C1 control characters (real whitespace ones are left for SPACES_RE)
control_re = re.compile("[\x00-\x08\x0e-\x1b\x7f-\x84\x86-\x9f]")
# \s already covers NBSP, narrow NBSP, thin space, tab, newline, ...
spaces_re = re.compile(r"\s+")

# ======================================================================
# Uzbek: old (1990s) Latin letters -> current alphabet
# (add more pairs here if you find other leftovers)
# ======================================================================
eski_lotin = {
    "\u015f": "sh",                # ş
    "\u0219": "sh",                # ș  (comma-below variant of ş)
    "\u00e7": "ch",                # ç
    "\u011f": "g" + apostroflar,    # ğ
    "\u014f": "o" + apostroflar,    # ŏ
}
eski_lotin_re = re.compile(
    "[" + "".join(eski_lotin) + "".join(k.upper() for k in eski_lotin) + "]"
)

def _eski_lotin_sub(m):
    ch = m.group(0)
    rep = eski_lotin[ch.lower()]
    if ch.islower():
        return rep
    s, i, j = m.string, m.start(), m.end()
    nxt = s[j] if j < len(s) else ""
    prv = s[i - 1] if i > 0 else ""
    # ŞAHAR -> SHAHAR (all caps),  Şahar -> Shahar
    if nxt.isupper() or prv.isupper():
        return rep.upper()
    return rep.capitalize()


# ======================================================================
# Apostrophes
# ======================================================================
_L = r"[^\W\d_]"  # any letter
# Every sign that can stand for an apostrophe in Uzbek text:
# ' ʻ ʼ ʽ ʾ ʿ ‘ ’ ‛ ` ´ ʹ ′ ‵ ˈ ˊ ˋ ՚
_apos_any = ("'\u02bb\u02bc\u02bd\u02be\u02bf\u2018\u2019\u201b`\u00b4"
             "\u02b9\u2032\u2035\u02c8\u02ca\u02cb\u055a")
# "where relatable": the sign touches a letter on at least one side
uz_apostrof_re = re.compile(
    "(?<=" + _L + ")[" + _apos_any + "]|[" + _apos_any + "](?=" + _L + ")"
)
# English side is always plain ASCII ': ’ and ʼ anywhere (it’s, students’),
# other look-alikes only between two letters (Oʻzbekiston, don`t)
en_apostrof_re = re.compile(
    "[\u2019\u02bc]|(?<=" + _L + ")[\u02bb\u2018`\u00b4\u02b9](?=" + _L + ")"
)

# ======================================================================
# Cyrillic
# ======================================================================
kiril_re = re.compile("[\u0400-\u052f]")
lotin_re = re.compile("[A-Za-z]")
token_re = re.compile(r"\S+")
# Cyrillic letters that look identical to Latin ones:
#   а е о р с у х к і ј ѕ   ->  a e o p c y x k i j s
#   А В Е К М Н О Р С Т Х І Ј Ѕ -> A B E K M H O P C T X I J S
_CYR = "\u0430\u0435\u043e\u0440\u0441\u0443\u0445\u043a\u0456\u0458\u0455"
_LAT = "aeopcyxkijs"
_CYR_UP = ("\u0410\u0412\u0415\u041a\u041c\u041d\u041e\u0420\u0421\u0422"
           "\u0425\u0406\u0408\u0405")
_LAT_UP = "ABEKMHOPCTXIJS"
HOMOGLYPHS = str.maketrans(_CYR + _CYR_UP, _LAT + _LAT_UP)

# Mojibake: "Ã©", "â€™", "�"
MOJIBAKE_RE = re.compile("\u00c3[\u0080-\u00bf]|\u00e2\u20ac|\ufffd")

# ======================================================================
# Numbers and punctuation spacing
# ======================================================================
# "3 . 5" -> "3.5"  (space BEFORE the dot is required, so that
# "in 2004. 5 people came" is NOT glued into "2004.5")
NUM_SPLIT_DOT_RE = re.compile(r"(\d)\s+\.\s*(?=\d)")
# "1 , 5" -> "1,5"   ("April 1, 2004" stays unchanged)
NUM_SPLIT_COMMA_RE = re.compile(r"(\d)\s+,\s*(?=\d)")
# "25 %" -> "25%"
PERCENT_RE = re.compile(r"(\d)\s+%")
SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([.,!?;:)\]}»])")
SPACE_AFTER_OPEN_RE = re.compile(r"([(\[{«])\s+")
# "Index,Himalayan" -> "Index, Himalayan"
NO_SPACE_AFTER_RE = re.compile(r"(?<=[^\W\d_])([,;])(?=[^\W\d_])")


def fix_homoglyphs(text: str) -> str:
    """Replace Cyrillic look-alikes inside tokens that mix Latin and Cyrillic."""
    def repl(m):
        tok = m.group(0)
        if kiril_re.search(tok) and lotin_re.search(tok):
            fixed = tok.translate(HOMOGLYPHS)
            if not kiril_re.search(fixed):  # only if fully repaired
                return fixed
        return tok
    return token_re.sub(repl, text)

def _prepare(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = korinmas_re.sub("", text)
    text = control_re.sub("", text)
    return fix_homoglyphs(text)


def _tidy(text: str) -> str:
    text = SPACES_RE.sub(" ", text)
    text = NUM_SPLIT_DOT_RE.sub(r"\1.", text)
    text = NUM_SPLIT_COMMA_RE.sub(r"\1,", text)
    text = PERCENT_RE.sub(r"\1%", text)
    text = SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    text = SPACE_AFTER_OPEN_RE.sub(r"\1", text)
    text = NO_SPACE_AFTER_RE.sub(r"\1 ", text)
    text = SPACES_RE.sub(" ", text)
    return text.strip()


# ======================================================================
# Uzbek Cyrillic -> Latin transliteration (current official alphabet)
# ======================================================================
# Letters that exist only in Uzbek Cyrillic (not in Russian). If a text has
# none of them we cannot tell Uzbek from Russian, so it is NOT transliterated.
UZ_CYR_SPECIFIC_RE = re.compile("[ўқғҳЎҚҒҲ]")  # ў қ ғ ҳ
_CYR_VOWELS = set("аеёиоуўэюяы")
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": APOSTROPHE, "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ў": "o" + APOSTROPHE, "қ": "q", "ғ": "g" + APOSTROPHE, "ҳ": "h",
}


def translit_uz(text: str) -> str:
    out = []
    for i, ch in enumerate(text):
        low = ch.lower()
        rep = _TRANSLIT.get(low)
        if rep is None:
            out.append(ch)
            continue
        if low == "е":  # е: "ye" at word start / after a vowel, else "e"
            prev = text[i - 1].lower() if i > 0 else " "
            if not prev.isalpha() or prev in _CYR_VOWELS:
                rep = "ye"
        if ch.isupper() and rep:
            nxt = text[i + 1] if i + 1 < len(text) else ""
            prv = text[i - 1] if i > 0 else ""
            if len(rep) > 1 and (nxt.isupper() or prv.isupper()):
                rep = rep.upper()          # ШАҲАР -> SHAHAR
            else:
                rep = rep[0].upper() + rep[1:]   # Шаҳар -> Shahar
        out.append(rep)
    return "".join(out)


# ======================================================================
# Russian: Latin look-alikes inside Cyrillic words -> Cyrillic
# ======================================================================
_RU_FIX = str.maketrans({
    "a": "а", "e": "е", "o": "о", "p": "р", "c": "с",
    "y": "у", "x": "х", "k": "к",
    "A": "А", "B": "В", "E": "Е", "K": "К", "M": "М",
    "H": "Н", "O": "О", "P": "Р", "C": "С", "T": "Т",
    "X": "Х", "Y": "У",
})


def fix_homoglyphs_ru(text: str) -> str:
    def repl(m):
        tok = m.group(0)
        if CYRILLIC_RE.search(tok) and LATIN_RE.search(tok):
            fixed = tok.translate(_RU_FIX)
            if not LATIN_RE.search(fixed):  # only if fully repaired
                return fixed
        return tok
    return TOKEN_RE.sub(repl, text)


# ======================================================================
# Cleaners (one per language)
# ======================================================================
def clean_en(text: str, translit: bool = False) -> str:
    text = _prepare(text)
    text = EN_APOS_RE.sub("'", text)
    return _tidy(text)


def clean_uz(text: str, translit: bool = False) -> str:
    text = unicodedata.normalize("NFC", text)
    # Uzbek written in Cyrillic -> Latin (before look-alike repair)
    if translit and CYRILLIC_RE.search(text) and UZ_CYR_SPECIFIC_RE.search(text):
        text = translit_uz(text)
    text = _prepare(text)
    text = OLD_LATIN_RE.sub(_old_latin_sub, text)
    text = UZ_APOS_RE.sub(APOSTROPHE, text)
    return _tidy(text)


def clean_ru(text: str, translit: bool = False) -> str:
    text = unicodedata.normalize("NFC", text)
    text = INVISIBLE_RE.sub("", text)
    text = CONTROL_RE.sub("", text)
    text = fix_homoglyphs_ru(text)
    return _tidy(text)


CLEANERS = {"eng": clean_en, "uzb": clean_uz, "rus": clean_ru}

# source_lang labels that may appear in the file -> our codes
LANG_ALIASES = {
    "eng": "eng", "en": "eng", "english": "eng",
    "uzb": "uzb", "uz": "uzb", "uzn": "uzb", "uzbek": "uzb",
    "rus": "rus", "ru": "rus", "russian": "rus",
}


# ======================================================================
# Row filtering
# ======================================================================
def reject_reason(src: str, tgt: str, src_lang: str, tgt_lang: str, args):
    if not src or not tgt:
        return "empty"
    if MOJIBAKE_RE.search(src) or MOJIBAKE_RE.search(tgt):
        return "mojibake"
    # Russian text must be Cyrillic; English / Uzbek (Latin) must not be.
    for text, lang in ((src, src_lang), (tgt, tgt_lang)):
        has_cyr = bool(CYRILLIC_RE.search(text))
        if lang == "rus":
            if not has_cyr:
                return "not_russian"
        elif has_cyr and args.cyrillic != "keep":
            # with --cyrillic translit, Uzbek Cyrillic was already converted;
            # whatever is still Cyrillic here is Russian / unclear -> drop
            return "cyrillic"
    if args.drop_identical and src.casefold() == tgt.casefold() and LATIN_RE.search(src):
        return "identical"
    if args.max_ratio:
        ratio = (len(tgt) + 1) / (len(src) + 1)
        if ratio > args.max_ratio or ratio < 1 / args.max_ratio:
            return "length_ratio"
    return None


def _digest(text: str) -> bytes:
    return hashlib.blake2b(text.encode("utf-8"), digest_size=16).digest()


# ======================================================================
# Command line + pipeline
# ======================================================================
def build_parser(default_output: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Format a translation dataset into JSONL.")
    ap.add_argument("-i", "--input", default="data.csv")
    ap.add_argument("-o", "--output", default=default_output)
    ap.add_argument("--delimiter", default="\t",
                    help="column separator of the input (default: tab)")
    ap.add_argument("--keep-duplicates", action="store_true",
                    help="do not remove duplicate (source, translation) pairs")
    ap.add_argument("--dedupe-source", action="store_true",
                    help="also keep only the first translation of each source sentence")
    ap.add_argument("--cyrillic", choices=["drop", "translit", "keep"], default="drop",
                    help="Cyrillic in an English/Uzbek side: drop the row (default); "
                         "translit = convert Uzbek Cyrillic (has ў қ ғ ҳ) to Latin, drop the "
                         "rest; keep = do nothing")
    ap.add_argument("--drop-identical", action="store_true",
                    help="drop rows where source == translation")
    ap.add_argument("--max-ratio", type=float, default=0.0,
                    help="drop rows whose length ratio exceeds this, e.g. 3.5 (0 = off)")
    ap.add_argument("--min-confidence", type=float, default=None,
                    help="drop rows with confidence_score below this (missing score = drop)")
    ap.add_argument("--any-lang", action="store_true",
                    help="do not filter by source_lang (by default only rows of the "
                         "expected input language are used, the rest are skipped)")
    ap.add_argument("--swap", action="store_true",
                    help="input is the OTHER direction (e.g. eng source, uzb translation "
                         "but you want uzb-eng): swap source_texts and translation")
    ap.add_argument("--rejects", default=None,
                    help="write dropped rows with the reason to this JSONL file")
    return ap


def run(args, *, src_lang, tgt_lang):
    delim = "\t" if args.delimiter in ("\\t", "tab") else args.delimiter
    translit = args.cyrillic == "translit"
    clean_src_fn, clean_tgt_fn = CLEANERS[src_lang], CLEANERS[tgt_lang]
    # with --swap the input's own source_lang is the *target* language here
    expected_in = tgt_lang if args.swap else src_lang
    stats, langs = Counter(), Counter()
    seen_pairs, seen_src = set(), set()
    rej = open(args.rejects, "w", encoding="utf-8", newline="\n") if args.rejects else None

    def log_reject(reason, s, t):
        if rej:
            rej.write(json.dumps({"reason": reason, "source": s, "translation": t},
                                 ensure_ascii=False) + "\n")

    # utf-8-sig strips a BOM so the first column name is not corrupted
    with open(args.input, encoding="utf-8-sig", errors="replace", newline="") as fin, \
         open(args.output, "w", encoding="utf-8", newline="\n") as fout:
        reader = csv.DictReader(fin, delimiter=delim, quoting=csv.QUOTE_NONE)

        needed = {"source_lang", "source_texts", "translation"}
        missing = needed - set(reader.fieldnames or [])
        if missing:
            sys.exit(f"Missing columns {sorted(missing)}; found {reader.fieldnames}")

        for row in reader:
            stats["read"] += 1
            src_raw = row.get("source_texts")
            tgt_raw = row.get("translation")

            # a tab inside the text (extra field) or a too-short row
            if None in row or src_raw is None or tgt_raw is None:
                stats["dropped_malformed"] += 1
                log_reject("malformed", src_raw, tgt_raw)
                continue

            if args.swap:
                src_raw, tgt_raw = tgt_raw, src_raw

            lang_raw = (row.get("source_lang") or "").strip().lower()
            lang = LANG_ALIASES.get(lang_raw, lang_raw)
            langs[lang] += 1
            # rows of other languages (e.g. 'rus' rows while building eng-uzb)
            # are simply not part of this output
            if not args.any_lang and lang != expected_in:
                stats["skipped_other_lang"] += 1
                continue

            if args.min_confidence is not None:
                try:
                    conf = float((row.get("confidence_score") or "").strip())
                except ValueError:
                    conf = None
                if conf is None or conf < args.min_confidence:
                    stats["dropped_low_confidence"] += 1
                    log_reject("low_confidence", src_raw, tgt_raw)
                    continue

            src = clean_src_fn(src_raw, translit)
            tgt = clean_tgt_fn(tgt_raw, translit)
            if src != src_raw:
                stats["source_changed"] += 1
            if tgt != tgt_raw:
                stats["translation_changed"] += 1

            reason = reject_reason(src, tgt, src_lang, tgt_lang, args)
            if reason:
                stats["dropped_" + reason] += 1
                log_reject(reason, src_raw, tgt_raw)
                continue

            if not args.keep_duplicates:
                key = _digest(src + "\t" + tgt)
                if key in seen_pairs:
                    stats["dropped_duplicate"] += 1
                    continue
                seen_pairs.add(key)
            if args.dedupe_source:
                key = _digest(src.casefold())
                if key in seen_src:
                    stats["dropped_same_source"] += 1
                    continue
                seen_src.add(key)

            record = {
                "source_lang": src_lang,
                "source_texts": src,
                "translation_lang": tgt_lang,
                "translation": tgt,
            }
            fout.write(json.dumps(record, ensure_ascii=False) + "\n")
            stats["written"] += 1

            if stats["read"] % 200_000 == 0:
                print(f"  {stats['read']:,} rows read...", flush=True)

    if rej:
        rej.close()

    print("\nResult:")
    keys = ["read", "skipped_other_lang", "source_changed", "translation_changed"] + \
        sorted(k for k in stats if k.startswith("dropped_")) + ["written"]
    for k in keys:
        print(f"  {k:24s} {stats[k]:>12,}")

    print("\nsource_lang values found in the input:")
    for k, v in langs.most_common():
        mark = "  <- used" if (k == expected_in or args.any_lang) else ""
        print(f"  {k or '(empty)':24s} {v:>12,}{mark}")
    if not args.any_lang and langs[expected_in] == 0:
        print(f"\n  WARNING: no rows with source_lang '{expected_in}' were found, so "
              f"nothing was written. Check the labels above"
              f"{'' if args.swap else ' (or use --swap)'}.")
    print(f"\nSaved: {args.output}")

      