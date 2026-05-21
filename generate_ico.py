from svglib.svglib import svg2rlg
from reportlab.graphics import renderPM
from PIL import Image
import os

svg_path = 'tubecli/extensions/webui/static/logo.svg'
png_path = 'temp_logo.png'
ico_path = 'logo.ico'

drawing = svg2rlg(svg_path)
renderPM.drawToFile(drawing, png_path, fmt='PNG')

img = Image.open(png_path)
# Ensure square and transparency
sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
img.save(ico_path, format='ICO', sizes=sizes)

print('Generated logo.ico')
