import test from "node:test";
import assert from "node:assert/strict";

import { bestMatchFor, collectCandidateNames, formatBytes, parseSourceReference } from "../src/utils.js";

test("collectCandidateNames trims complete rows and reports partial rows", () => {
  const result = collectCandidateNames([
    { firstName: " María ", lastName: " González " },
    { firstName: "Robert", lastName: "" },
    { firstName: "", lastName: "" },
  ]);
  assert.deepEqual(result.names, [{ first_name: "María", last_name: "González" }]);
  assert.deepEqual(result.incompleteIndices, [1]);
});

test("bestMatchFor selects the highest full-name score", () => {
  const matches = [
    { extracted_name: "Robert Chen", matched_name: "Robert Chan", score: 0.91 },
    { extracted_name: "Robert Chen", matched_name: "Robert Chen", score: 0.99 },
    { extracted_name: "Sarah Williams", matched_name: "Sara Williams", score: 0.96 },
  ];
  assert.equal(bestMatchFor("Robert Chen", matches).matched_name, "Robert Chen");
  assert.equal(bestMatchFor("Unknown", matches), null);
});

test("parseSourceReference exposes verified source metadata", () => {
  assert.deepEqual(
    parseSourceReference("[S1] meeting_minutes.pdf · page 2 · New Business"),
    { id: "S1", filename: "meeting_minutes.pdf", location: "page 2 · New Business" },
  );
});

test("formatBytes uses readable binary units", () => {
  assert.equal(formatBytes(0), "0 B");
  assert.equal(formatBytes(1536), "1.50 KB");
  assert.equal(formatBytes(12 * 1024 * 1024), "12.0 MB");
});
