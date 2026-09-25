import assert from "node:assert/strict";
import test from "node:test";

import { boxesByPage, matchedNames, namesFromRows, toViewport } from "./boxes.js";

test("a box in points lands on the same spot of a page rendered at any scale", () => {
  const box = { page_number: 0, x: 76.8, y: 98.88, width: 88.32, height: 9.12 };

  assert.deepEqual(toViewport(box, 1), { left: 76.8, top: 98.88, width: 88.32, height: 9.12 });
  const scaled = toViewport(box, 1.5);
  assert.ok(Math.abs(scaled.left - 115.2) < 1e-9);
  assert.ok(Math.abs(scaled.top - 148.32) < 1e-9);
  assert.ok(Math.abs(scaled.width - 132.48) < 1e-9);
  assert.ok(Math.abs(scaled.height - 13.68) < 1e-9);
});

test("every occurrence keeps its own page and only matched names are flagged", () => {
  const extracted = [
    { name: "Anna Berg", bounding_box: { page_number: 0, x: 1, y: 1, width: 1, height: 1 } },
    { name: "Omar Haddad", bounding_box: { page_number: 1, x: 2, y: 2, width: 1, height: 1 } },
    { name: "Anna Berg", bounding_box: { page_number: 1, x: 3, y: 3, width: 1, height: 1 } },
  ];

  const pages = boxesByPage(extracted, matchedNames([{ extracted_name: "Anna Berg" }]));

  assert.deepEqual([...pages.keys()], [0, 1]);
  assert.deepEqual(
    pages.get(1).map((b) => [b.index, b.name, b.matched]),
    [[1, "Omar Haddad", false], [2, "Anna Berg", true]],
  );
});

test("half-filled name rows are rejected and blank rows ignored", () => {
  assert.deepEqual(
    namesFromRows([{ first: " María ", last: "González" }, { first: "", last: " " }]),
    [{ first_name: "María", last_name: "González" }],
  );
  assert.throws(() => namesFromRows([{ first: "Anna", last: "" }]));
});
