/**
 * Pure helpers that place API boxes on rendered pages.
 *
 * API boxes are in PDF points (72 per inch) with the origin at the top-left
 * of the displayed page, the same space a pdf.js viewport renders, so a box
 * only needs scaling by the viewport scale.
 */

/**
 * Converts a box in PDF points to CSS pixels on a page rendered at `scale`.
 * @param {{x: number, y: number, width: number, height: number}} box
 * @param {number} scale CSS pixels per PDF point.
 * @returns {{left: number, top: number, width: number, height: number}}
 */
export function toViewport(box, scale) {
  return {
    left: box.x * scale,
    top: box.y * scale,
    width: box.width * scale,
    height: box.height * scale,
  };
}

/**
 * Names in the extraction that fuzzy-matched a queried name.
 * @param {{extracted_name: string}[]} fuzzyMatches
 * @returns {Set<string>}
 */
export function matchedNames(fuzzyMatches) {
  return new Set(fuzzyMatches.map((m) => m.extracted_name));
}

/**
 * Groups extracted names by 0-based page, flagging the matched ones.
 * @param {{name: string, bounding_box: {page_number: number}}[]} extracted
 * @param {Set<string>} matched
 * @returns {Map<number, {index: number, name: string, box: object, matched: boolean}[]>}
 */
export function boxesByPage(extracted, matched) {
  const pages = new Map();
  extracted.forEach((item, index) => {
    const page = item.bounding_box.page_number;
    if (!pages.has(page)) pages.set(page, []);
    pages.get(page).push({
      index,
      name: item.name,
      box: item.bounding_box,
      matched: matched.has(item.name),
    });
  });
  return pages;
}

/**
 * Turns the name rows of the form into the API's `names` list.
 * Blank rows are skipped; a row with only one part is an error.
 * @param {{first: string, last: string}[]} rows
 * @returns {{first_name: string, last_name: string}[]}
 */
export function namesFromRows(rows) {
  const names = [];
  for (const row of rows) {
    const first = row.first.trim();
    const last = row.last.trim();
    if (!first && !last) continue;
    if (!first || !last) {
      throw new Error("Every name needs both a first and a last name.");
    }
    names.push({ first_name: first, last_name: last });
  }
  return names;
}
