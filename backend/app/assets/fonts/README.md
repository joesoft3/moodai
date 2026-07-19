# Bundled fonts

`DejaVuSans-Bold.ttf` ships inside the repo so the 🎨 design studio's text
rendering (ffmpeg `drawtext`) works on hosts with no system fonts — Vercel /
AWS Lambda images, minimal containers, fresh VMs.

DejaVu fonts are licensed under the Bitstream Vera / Arev-style license:
free to use, embed, and redistribute (modified or unmodified) provided the
fonts are not sold by themselves. Full text:
https://dejavu-fonts.github.io/License.html

The rasterizer prefers this bundled file first, then falls back to common
system paths (see `_FONT_CANDIDATES` in `app/services/designer.py`).
