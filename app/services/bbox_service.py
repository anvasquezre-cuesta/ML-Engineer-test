"""Name-to-box matching plus the single pixel→point conversion (AD-4)."""


def pixels_to_points(words: list[dict], dpi: int) -> list[dict]:
    """Convert rendered-image pixel boxes to PDF points (72/inch). The only
    place in the codebase that divides by DPI (AD-4)."""
    scale = 72 / dpi
    return [
        {
            "word": w["word"],
            "page": w["page"],
            "x": w["x"] * scale,
            "y": w["y"] * scale,
            "width": w["width"] * scale,
            "height": w["height"] * scale,
        }
        for w in words
    ]


def find_name_bounding_boxes(name: str, words: list[dict]) -> list[dict]:
    """Match a name against point-space word boxes; return one merged box per
    occurrence. Case-insensitive; only sequence-adjacent words merge."""
    name_lower = name.lower().split()
    if not name_lower:
        return []

    results = []
    n_words = len(words)
    for i in range(n_words):
        if words[i]["word"].lower() != name_lower[0]:
            continue
        if len(name_lower) == 1:
            results.append({
                "name": name,
                "word": words[i]["word"],
                "page": words[i]["page"],
                "x": words[i]["x"],
                "y": words[i]["y"],
                "width": words[i]["width"],
                "height": words[i]["height"],
            })
        else:
            # Multi-word name: subsequent words must match in sequence
            j = i + 1
            k = 1
            while k < len(name_lower) and j < n_words:
                if words[j]["word"].lower() == name_lower[k]:
                    k += 1
                    j += 1
                else:
                    break
            if k == len(name_lower):
                # Full name matched across words i..j-1: merge enclosing box
                min_x = min(words[m]["x"] for m in range(i, j))
                min_y = min(words[m]["y"] for m in range(i, j))
                max_x = max(words[m]["x"] + words[m]["width"] for m in range(i, j))
                max_y = max(words[m]["y"] + words[m]["height"] for m in range(i, j))
                results.append({
                    "name": name,
                    "page": words[i]["page"],
                    "x": min_x,
                    "y": min_y,
                    "width": max_x - min_x,
                    "height": max_y - min_y,
                })
    return results
