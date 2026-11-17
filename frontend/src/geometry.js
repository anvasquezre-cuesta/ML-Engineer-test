/** Convert zero-based, unrotated crop-relative PDF boxes to screen percentages. */
export function displayBox(box, width, height, rotation) {
  const values = [box?.x, box?.y, box?.width, box?.height, width, height];
  if (!values.every((value) => typeof value === "number" && Number.isFinite(value)) ||
      width <= 0 || height <= 0 || box.width <= 0 || box.height <= 0 ||
      box.x < 0 || box.y < 0 || box.x + box.width > width + 0.001 ||
      box.y + box.height > height + 0.001 || ![0, 90, 180, 270].includes(rotation)) return null;

  let x = box.x, y = box.y, w = box.width, h = box.height;
  let displayWidth = width, displayHeight = height;
  if (rotation === 90) {
    x = height - box.y - box.height; y = box.x; w = box.height; h = box.width;
    displayWidth = height; displayHeight = width;
  } else if (rotation === 180) {
    x = width - box.x - box.width; y = height - box.y - box.height;
  } else if (rotation === 270) {
    x = box.y; y = width - box.x - box.width; w = box.height; h = box.width;
    displayWidth = height; displayHeight = width;
  }
  return {left: x / displayWidth * 100, top: y / displayHeight * 100,
          width: w / displayWidth * 100, height: h / displayHeight * 100};
}
