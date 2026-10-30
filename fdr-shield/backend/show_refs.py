from pathlib import Path
from PIL import Image, ImageDraw

files = list(Path('reference_formats').rglob('*.png'))
out = Image.new('RGB', (1400, 1200), '#ddd')
draw = ImageDraw.Draw(out)
for i, path in enumerate(files):
    image = Image.open(path).convert('RGB')
    image.thumbnail((690, 560))
    x, y = (i % 2) * 700, (i // 2) * 600
    out.paste(image, (x, y + 30))
    draw.text((x + 5, y + 5), path.as_posix(), fill='black')
out.save('C:/Users/DELL/.codex/visualizations/2026/10/26/01a17770-016e-7c72-ae5d-e005009de1b9/references.jpg')
