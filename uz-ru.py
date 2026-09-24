tmx_path="./hamza_1.0/uz-ru.tmx"

#with open(tmx_path, "r", encoding="utf-8") as my_file:
  #  content=my_file.read()

#print(content[:1000])

import os

print(os.path.exists(tmx_path))

import xml.etree.ElementTree as ET

tree = ET.parse(tmx_path)
root = tree.getroot()
print(root.tag)

