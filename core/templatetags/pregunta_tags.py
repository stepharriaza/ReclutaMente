import re

from django import template

register = template.Library()

IMG_URL = re.compile(
    r'https?://[^\s<>"\']+\.(?:png|jpe?g|gif|webp|svg)(?:\?[^\s<>"\']*)?',
    re.IGNORECASE,
)
IMG_PATH = re.compile(
    r'^(?:[\w.-]+/)*[\w.-]+\.(?:png|jpe?g|gif|webp|svg)$',
    re.IGNORECASE,
)


@register.filter
def bloques_pregunta(texto):
    if not texto:
        return []
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    bloques = []
    for linea in texto.split("\n"):
        stripped = linea.strip()
        if IMG_PATH.match(stripped):
            bloques.append({"tipo": "imagen", "valor": stripped, "externa": False})
            continue
        pos = 0
        encontrado = False
        for match in IMG_URL.finditer(linea):
            encontrado = True
            antes = linea[pos:match.start()]
            if antes.strip():
                bloques.append({"tipo": "texto", "valor": antes.strip()})
            bloques.append({"tipo": "imagen", "valor": match.group(0), "externa": True})
            pos = match.end()
        if encontrado:
            resto = linea[pos:]
            if resto.strip():
                bloques.append({"tipo": "texto", "valor": resto.strip()})
        else:
            bloques.append({"tipo": "texto", "valor": linea})

    unidos = []
    for bloque in bloques:
        if bloque["tipo"] == "texto" and unidos and unidos[-1]["tipo"] == "texto":
            unidos[-1]["valor"] += "\n" + bloque["valor"]
        else:
            unidos.append(bloque)
    return [b for b in unidos if not (b["tipo"] == "texto" and not b["valor"].strip())]
