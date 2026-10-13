from datasets import load_dataset

ds = load_dataset("Helsinki-NLP/multiun", "ru-zh")

import argparse
import re 
import unicodedata 
from collections import Counter

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