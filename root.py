pairs = []

for tu in root.iter("tu"):
    uz_text = None
    ru_text = None

    for tuv in tu.findall("tuv"):
        
        lang = tuv.attrib.get("{http://www.w3.org/XML/1998/namespace}lang")

        seg = tuv.find("seg")

        if seg is None:
            continue

        text = "".join(seg.itertext()).strip()

        if lang == "uz":
            uz_text = text

        elif lang == "ru":
            ru_text = text

    if uz_text and ru_text:
        pairs.append({
            "uz": uz_text,
            "ru": ru_text
        })

print("Количество пар:", len(pairs))