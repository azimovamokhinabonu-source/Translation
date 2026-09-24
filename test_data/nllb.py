import json
import torch 
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM 

tokenizer = AutoTokenizer.from_pretrained("facebook/nllb-200-3.3B") 
model = AutoModelForSeq2SeqLM.from_pretrained("facebook/nllb-200-3.3B", device_map="auto")