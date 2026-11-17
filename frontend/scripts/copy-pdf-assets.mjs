import {cpSync, mkdirSync} from "node:fs";
import {join} from "node:path";

const destination = "dist/pdfjs";
mkdirSync(destination, {recursive: true});
for (const directory of ["cmaps", "standard_fonts", "wasm"]) {
  cpSync(join("node_modules/pdfjs-dist", directory), join(destination, directory), {recursive: true});
}
