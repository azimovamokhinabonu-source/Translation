Sample for ru_zh.py: 

"""
JSONL (rus-xitoy parallel korpus) tozalash skripti.

Ishlatish (terminal):
    python clean_dataset.py input.jsonl output.jsonl
    python clean_dataset.py input.jsonl output.jsonl --keys ru zh

Agar --keys berilmasa, har bir qatordagi BARCHA matnli (str) maydonlar tozalanadi.
"""
import argparse
import json
import re
import unicodedata
from collections import Counter

# ---------- Regexlar va jadvallar ----------

# Ko'rinmas belgilar: zero-width space, BOM, soft hyphen va h.k.
INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff\u00ad]")
# Boshqaruv belgilari (\t \n \r dan tashqari)
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Barcha bo'shliq turlari (NBSP, tab, newline, ideografik bo'shliq va h.k.)
WHITESPACE_RE = re.compile(r"\s+")

# o' va g' (hamda ma'lumot, e'lon kabi) uchun apostrof variantlari
APOS_VARIANTS = "ʻʼ‘’`´′‵ʹ՚＇'"
APOS_RE = re.compile(rf"(?<=[A-Za-z])[{re.escape(APOS_VARIANTS)}](?=[A-Za-z]|\b)")

# Fullwidth raqam va lotin harflarini oddiy ASCII ga o'tkazish (０１２ -> 012, Ａ -> A)
FULLWIDTH_MAP = {c: c - 0xFEE0 for c in range(0xFF10, 0xFF1A)}  # 0-9
FULLWIDTH_MAP.update({c: c - 0xFEE0 for c in range(0xFF21, 0xFF3B)})  # A-Z
FULLWIDTH_MAP.update({c: c - 0xFEE0 for c in range(0xFF41, 0xFF5B)})  # a-z
# Arab-hind raqamlari (٠-٩) va fors raqamlari (۰-۹)
FULLWIDTH_MAP.update({c: 0x30 + (c - 0x0660) for c in range(0x0660, 0x066A)})
FULLWIDTH_MAP.update({c: 0x30 + (c - 0x06F0) for c in range(0x06F0, 0x06FA)})

# Xitoy harflari va xitoy tinish belgilari orasidagi ortiqcha bo'shliq
CJK = r"\u4e00-\u9fff\u3400-\u4dbf\u3000-\u303f\uff00-\uffef"
CJK_SPACE_RE = re.compile(rf"(?<=[{CJK}])\s+(?=[{CJK}])")

# Tinish belgilaridan oldingi ortiqcha bo'shliq:  "salom ."  ->  "salom."
SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([.,;:!?%)\]])")


def clean_text(text: str) -> str:
    # 1) Unicode normalizatsiya (NFC: kombinatsiyalangan belgilarni bitta qiladi,
    #    xitoycha tinish belgilarini buzmaydi)
    text = unicodedata.normalize("NFC", text)

    # 2) Ko'rinmas va boshqaruv belgilarni olib tashlash
    text = INVISIBLE_RE.sub("", text)
    text = CONTROL_RE.sub("", text)

    # 3) Fullwidth/arab raqamlar va harflarni oddiy ko'rinishga keltirish
    text = text.translate(FULLWIDTH_MAP)

    # 4) Apostrof: o‘ o’ oʻ g` ... -> o' g'
    text = APOS_RE.sub("'", text)

    # 5) Barcha bo'shliqlarni (NBSP, tab, \n ...) bitta oddiy probelga
    text = WHITESPACE_RE.sub(" ", text)

    # 6) Xitoycha matn ichidagi ortiqcha probellarni olib tashlash
    text = CJK_SPACE_RE.sub("", text)

    # 7) Tinish belgilaridan oldingi probelni olib tashlash
    text = SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)

    # 8) Trim
    return text.strip()


def clean_value(value, keys):
    """dict ichidagi matnlarni rekursiv tozalaydi."""
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, dict):
        return {
            k: (clean_value(v, None) if (keys is None or k in keys) else v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [clean_value(v, keys) for v in value]
    return value


def text_fields(obj, keys):
    """Bo'sh-bo'shmasligini va dublikatni tekshirish uchun matnlar ro'yxati."""
    if keys:
        return [obj.get(k) for k in keys]
    return [v for v in obj.values() if isinstance(v, str)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--keys", nargs="*", default=None,
                    help="Tozalanadigan maydonlar, masalan: --keys ru zh")
    ap.add_argument("--keep-duplicates", action="store_true",
                    help="Dublikat juftliklarni o'chirmaslik")
    args = ap.parse_args()

    stats = Counter()
    seen = set()

    with open(args.input, "r", encoding="utf-8-sig") as fin, \
         open(args.output, "w", encoding="utf-8") as fout:
        for line_no, line in enumerate(fin, 1):
            line = line.strip()
            if not line:
                stats["bo'sh qator"] += 1
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                stats["buzuq JSON"] += 1
                print(f"[!] {line_no}-qator JSON emas, o'tkazib yuborildi")
                continue

            stats["jami"] += 1
            if line_no == 1 and args.keys is None:
                print("Topilgan maydonlar:", list(obj.keys()))

            obj = clean_value(obj, args.keys)

            fields = text_fields(obj, args.keys)
            if not fields or any(not f for f in fields):
                stats["bo'sh matn (o'chirildi)"] += 1
                continue

            if not args.keep_duplicates:
                key = tuple(fields)
                if key in seen:
                    stats["dublikat (o'chirildi)"] += 1
                    continue
                seen.add(key)

            fout.write(json.dumps(obj, ensure_ascii=False) + "\n")
            stats["saqlandi"] += 1

    print("\n--- Natija ---")
    for k, v in stats.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()