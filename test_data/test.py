import json
import torch 

from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

tokenizer = AutoTokenizer.from_pretrained("google/madlad400-10b-mt")
model = AutoModelForSeq2SeqLM.from_pretrained("google/madlad400-10b-mt", device_map="auto")


input_path="al_manifest_100.jsonl"
data =[]


with open(input_path, "r", encoding="utf-8") as my_file:
    for line in my_file:
        data.append(json.loads(line))

print("Barcha ma'lumotlar soni:", len(data))

til="en"

rezultat=[]
for i,item in enumerate(data):
    tekst=item["text"]
    
    input_text=f"<2{til}>{tekst}"
    
    inputs = tokenizer(
    input_text,
    return_tensors="pt")

    inputs={
        key: value.to(model.device) 
        for key, value in inputs.items()
    }

    with torch.no_grad(): 
        outputs=model.generate(
                **inputs,
                max_new_tokens=256
    )
    tarjima=tokenizer.decode(
        outputs[0], 
        skip_special_tokens=True
    )
    print(
        f"original tekst: {tekst}\n"
        f"tarjima qilingan tekst: {tarjima}")

    
     # rezultat = {
       # "tekst": tekst,
      #  "translation": tarjima 
    #}
    #rezultat.append(rezultat)


     


