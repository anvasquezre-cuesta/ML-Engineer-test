# Design sources

`design.html` is the source of the root `DESIGN.pdf`; it shows the `*.svg` files next to it,
which `DESIGN.md` uses too. To rebuild the PDF on Windows:

```bash
"/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" --headless=new \
  --no-pdf-header-footer --print-to-pdf="$PWD/DESIGN.pdf" "file:///$PWD/docs/design/design.html"
```
