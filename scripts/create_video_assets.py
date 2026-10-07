"""Cria quadros estáticos para o vídeo demonstrativo do Projeto Final."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "Projeto_Final_Artefatos" / "video_frames"
OUT.mkdir(parents=True, exist_ok=True)
JSON_PATH = ROOT / "evidence" / "demo_analysis_offline.json"
data = json.loads(JSON_PATH.read_text(encoding="utf-8"))

W, H = 1280, 720
BG = "#0B132B"
SURFACE = "#1C2541"
SURFACE2 = "#111E3A"
WHITE = "#FFFFFF"
MUTED = "#A0C4FF"
AMBER = "#FFB703"
LINE = "#3A506B"
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")


def font(name: str, size: int):
    candidates = {
        "regular": FONT_DIR / "DejaVuSans.ttf",
        "bold": FONT_DIR / "DejaVuSans-Bold.ttf",
        "mono": FONT_DIR / "DejaVuSansMono.ttf",
    }
    return ImageFont.truetype(str(candidates[name]), size)


def base(title: str, subtitle: str, number: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    draw.line((60, 42, 210, 42), fill=AMBER, width=4)
    draw.text((60, 58), title, font=font("bold", 36), fill=WHITE)
    draw.text((60, 120), subtitle, font=font("regular", 21), fill=MUTED)
    draw.text((60, 680), number, font=font("regular", 14), fill=MUTED)
    draw.text((1070, 680), "INSURMINDS", font=font("regular", 14), fill=MUTED)
    return image, draw


def card(draw, box, title, value, note, accent=AMBER):
    x1, y1, x2, y2 = box
    draw.rectangle(box, fill=SURFACE, outline=LINE, width=1)
    draw.rectangle((x1, y1, x2, y1 + 4), fill=accent)
    draw.text((x1 + 22, y1 + 24), title, font=font("regular", 16), fill=MUTED)
    draw.text((x1 + 22, y1 + 62), value, font=font("bold", 34), fill=WHITE)
    draw.text((x1 + 22, y2 - 42), note, font=font("regular", 15), fill=MUTED)


def save(image: Image.Image, index: int):
    image.save(OUT / f"frame_{index:02d}.png")


# Frame 1 — cover
image = Image.new("RGB", (W, H), BG)
draw = ImageDraw.Draw(image)
for x in [850, 980, 1110]:
    draw.line((x, 0, x, H), fill=LINE, width=1)
draw.line((780, 165, 1210, 165), fill=LINE, width=1)
draw.line((780, 430, 1210, 430), fill=LINE, width=1)
draw.line((70, 170, 240, 170), fill=AMBER, width=4)
draw.text((70, 105), "PROJETO FINAL · INSURMINDS", font=font("regular", 16), fill=MUTED)
draw.text((70, 215), "D&O Policy", font=font("bold", 58), fill=WHITE)
draw.text((70, 280), "Intelligence", font=font("bold", 58), fill=AMBER)
draw.text((74, 385), "Análise e comparação explicável de apólices D&O", font=font("regular", 25), fill=MUTED)
draw.text((74, 465), "MVP FUNCIONAL · DEMONSTRAÇÃO", font=font("regular", 16), fill=AMBER)
for x, label, fill in [(820, "PDF", SURFACE), (972, "IA", SURFACE), (1124, "COMPARE", AMBER)]:
    draw.rectangle((x, 520, x + 110, 584), fill=fill, outline=LINE, width=1)
    draw.text((x + 55, 552), label, font=font("bold", 15), fill=BG if fill == AMBER else WHITE, anchor="mm")
draw.line((930, 552, 972, 552), fill=AMBER, width=2)
draw.line((1082, 552, 1124, 552), fill=AMBER, width=2)
draw.text((60, 680), "01", font=font("regular", 14), fill=MUTED)
draw.text((1070, 680), "INSURMINDS", font=font("regular", 14), fill=MUTED)
save(image, 1)

# Frame 2 — problem
image, draw = base(
    "O problema", "Apólices extensas escondem diferenças críticas em limites, coberturas e exclusões.", "02"
)
draw.rectangle((70, 190, 500, 550), fill=SURFACE, outline=LINE, width=1)
draw.rectangle((70, 190, 500, 245), fill="#263452")
draw.text((95, 208), "CONDIÇÕES GERAIS · D&O", font=font("regular", 15), fill=WHITE)
for y, w in [(285, 310), (320, 370), (355, 280), (390, 335), (425, 250), (475, 370), (510, 300)]:
    draw.line((105, y, 105 + w, y), fill=MUTED, width=3)
draw.rectangle((630, 275, 1190, 500), fill=SURFACE2, outline=AMBER, width=2)
draw.text((660, 300), "COMPARAÇÃO MANUAL", font=font("bold", 17), fill=AMBER)
for y, label in [(350, "limites"), (395, "franquias"), (440, "exclusões")]:
    draw.text((660, y), label, font=font("regular", 19), fill=WHITE)
    draw.text((1000, y), "?  /  ?", font=font("mono", 19), fill=MUTED)
draw.text(
    (70, 600),
    "O custo oculto: horas de leitura mecânica antes da análise de negócio.",
    font=font("regular", 20),
    fill=AMBER,
)
save(image, 2)

# Frame 3 — flow
image, draw = base("Do documento à decisão", "Uma jornada linear, modular e revisável.", "03")
steps = [
    (80, "01", "Receber"),
    (270, "02", "Extrair"),
    (460, "03", "Estruturar"),
    (650, "04", "Armazenar"),
    (840, "05", "Comparar"),
    (1030, "06", "Revisar"),
]
for index, (x, num, label) in enumerate(steps):
    fill = AMBER if index == 5 else SURFACE
    text_fill = BG if index == 5 else WHITE
    draw.rectangle((x, 270, x + 140, 420), fill=fill, outline=LINE, width=1)
    draw.text((x + 18, 292), num, font=font("bold", 16), fill=BG if index == 5 else AMBER)
    draw.text((x + 70, 345), label, font=font("bold", 18), fill=text_fill, anchor="mm")
    if index < len(steps) - 1:
        draw.line((x + 140, 345, x + 190, 345), fill=AMBER if index == 4 else LINE, width=3)
draw.rectangle((80, 510, 1170, 580), fill=SURFACE2, outline=LINE, width=1)
draw.text((105, 532), "A decisão continua humana, documentada e revisável.", font=font("regular", 21), fill=WHITE)
save(image, 3)

# Frame 4 — comparison
image, draw = base("Comparação explicável", "Valores, status, páginas e trechos de origem em uma única tela.", "04")
x0, y0, x1, y1 = 70, 205, 1210, 555
draw.rectangle((x0, y0, x1, y1), fill=SURFACE, outline=LINE, width=1)
cols = [70, 390, 675, 960, 1210]
headers = ["CAMPO", "APÓLICE A", "APÓLICE B", "STATUS"]
for i, head in enumerate(headers):
    draw.text((cols[i] + 18, y0 + 20), head, font=font("bold", 15), fill=AMBER)
rows = [
    ("Limite máximo", "R$ 10 mi", "R$ 15 mi"),
    ("Franquia", "R$ 50 mil", "R$ 100 mil"),
    ("Âmbito geográfico", "Sem EUA/Canadá", "Inclui EUA/Canadá"),
    ("Período adicional", "24 meses", "36 meses"),
    ("Cobertura C", "Não incluída", "Incluída"),
]
for idx, (label, a, b) in enumerate(rows):
    y = y0 + 68 + idx * 48
    draw.line((x0 + 12, y - 12, x1 - 12, y - 12), fill=LINE, width=1)
    draw.text((cols[0] + 18, y), label, font=font("regular", 16), fill=WHITE)
    draw.text((cols[1] + 18, y), a, font=font("regular", 16), fill=WHITE)
    draw.text((cols[2] + 18, y), b, font=font("regular", 16), fill=WHITE)
    draw.text((cols[3] + 18, y), "DIFERENTE", font=font("bold", 14), fill=AMBER)
draw.text((70, 595), "Evidência por página: A:2 / B:2 ou A:3 / B:3", font=font("regular", 18), fill=MUTED)
save(image, 4)

# Frame 5 — results
image, draw = base("Resultado validado", "Execução local com corpus sintético, testes e provider de IA.", "05")
metrics = [(70, "2", "documentos"), (350, "6", "páginas"), (630, "19", "campos"), (910, "11", "diferenças")]
for x, value, label in metrics:
    draw.rectangle((x, 210, x + 240, 420), fill=SURFACE, outline=LINE, width=1)
    draw.rectangle((x, 210, x + 240, 214), fill=AMBER)
    draw.text((x + 22, 250), value, font=font("bold", 52), fill=AMBER)
    draw.text((x + 22, 335), label, font=font("regular", 20), fill=WHITE)
draw.rectangle((70, 505, 1150, 600), fill=SURFACE2, outline=LINE, width=1)
draw.text((95, 525), "6 testes automatizados aprovados", font=font("bold", 21), fill=AMBER)
draw.text(
    (95, 565),
    "R$ 10 mi vs. R$ 15 mi · R$ 50 mil vs. R$ 100 mil · 24 vs. 36 meses",
    font=font("regular", 18),
    fill=WHITE,
)
save(image, 5)

print(f"Frames gerados em {OUT}")
