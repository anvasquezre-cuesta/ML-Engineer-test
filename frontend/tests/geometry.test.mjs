import test from "node:test";
import assert from "node:assert/strict";
import {displayBox} from "../src/geometry.js";

const box = {x: 10, y: 20, width: 30, height: 40};
for (const [rotation, expected] of [
  [0, {left: 5, top: 20, width: 15, height: 40}],
  [90, {left: 40, top: 5, width: 40, height: 15}],
  [180, {left: 80, top: 40, width: 15, height: 40}],
  [270, {left: 20, top: 80, width: 40, height: 15}],
]) {
  test(`maps unrotated crop-relative boxes at ${rotation}°`, () => {
    assert.deepEqual(displayBox(box, 200, 100, rotation), expected);
  });
}

test("rejects invalid coordinates and unsupported page rotation", () => {
  assert.equal(displayBox({...box, x: -1}, 200, 100, 0), null);
  assert.equal(displayBox({...box, width: Number.NaN}, 200, 100, 0), null);
  assert.equal(displayBox({...box, x: 199}, 200, 100, 0), null);
  assert.equal(displayBox(box, 200, 100, 45), null);
  assert.equal(displayBox(null, 200, 100, 0), null);
});
