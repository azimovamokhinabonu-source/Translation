import json
import torch 

from transformers import AutoTokenizer, AutoModelForCausalLM

tokenizer = AutoTokenizer.from_pretrained("nvidia/Riva-Translate-4B-Instruct-v2")
model = AutoModelForCausalLM.from_pretrained("nvidia/Riva-Translate-4B-Instruct-v2", device_map="auto")

input_path="al_manifest_100.jsonl"

data =[]

with open(input_path, "r", encoding="utf-8") as my_file:
    for line in my_file:
        data.append(json.loads(line))


for i, item in enumerate(data):
    tekst=item["text"]
    messages = [
        {
            "role": "user", 
            "content": f"Translate the following Uzbek text into English: {tekst}"
            }
    ]
    
    inputs = tokenizer.apply_chat_template(
    	messages,
    	add_generation_prompt=True,
    	tokenize=True,
    	return_dict=True,
    	return_tensors="pt",
    ).to(model.device)

    with torch.no_grad():
        outputs=model.generate(
            **inputs, 
            max_new_tokens=256
        )
    tarjima=tokenizer.decode(
        outputs[0][inputs["input_ids"].shape[-1]:],
        skip_special_tokens=True
    )
    
    print(f"Original tekst: {tekst}")
    print(f"Tarjima qilingan tekst: {tarjima}")
    qator="-"*25
    print(qator)


    