from datasets import load_dataset

ds = load_dataset("Helsinki-NLP/multiun", "ru-zh")

import argparse
import hashlib
import json
import sys
import re 
import unicodedata 
from collections import Counter


# ---------------------------------------------------------
# Konsol encoding
# ---------------------------------------------------------

# Windows kabi muhitlarda stdout UTF-8 bo'lmasa,
# Unicode belgilarni print qilishda xato chiqmasligi uchun.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(
        encoding = "utf-8", 
        errors="replace"
    )

# ---------------------------------------------------------
# Asosiy konstantalar
# ---------------------------------------------------------

# UTF-8 BOM:
# ayrim fayllarning birinchi qatori shundan boshlanishi mumkin.
UTF8_BOM = b"\xef\xbb\xbf"

# Unicode replacement character:
#
#     �
#
# Bu odatda matn noto'g'ri decode qilinganini bildiradi.

replacement_char = "\ufffd"
# ---------------------------------------------------------
# Regexlar
# ---------------------------------------------------------

# Vertical tab, form feed, next line,
# Unicode line separator va paragraph separator.
#
# Ularni o'chirib yubormaymiz, probelga aylantiramiz.
# Aks holda ikkita so'z bir-biriga yopishib qolishi mumkin.
 line_sepe















# ---------- Regexlar va jadvallar ----------

input_path= mohina/test_ru_zh/multiun_ru_zh.jsonl 

# Ko'rinmas belgilar: zero-width space, BOM, soft hyphen va h.k.
korinmas_belgi= re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff\u00ad]")
# Boshqaruv belgilari (\t \n \r dan tashqari)
boshqaruv_belgi = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Barcha bo'shliq turlari (NBSP, tab, newline, ideografik bo'shliq va h.k.)
boshliq = re.compile(r"\s+")

# o' va g' (hamda ma'lumot, e'lon kabi) uchun apostrof variantlari
apostroflar="ʻʼ‘’`´′‵ʹ՚＇'"
apos_re= re.compile(rf"(?<=[A-Za-z])[{re.escape(apostroflar)}](?=[A-Za-z]| 