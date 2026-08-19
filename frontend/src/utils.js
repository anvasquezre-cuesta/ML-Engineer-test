export function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) return "Unknown size";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = units[0];
  for (let index = 1; value >= 1024 && index < units.length; index += 1) {
    value /= 1024;
    unit = units[index];
  }
  return `${value >= 10 ? value.toFixed(1) : value.toFixed(2)} ${unit}`;
}

export function collectCandidateNames(rows) {
  const names = [];
  const incompleteIndices = [];
  rows.forEach((row, index) => {
    const firstName = row.firstName.trim();
    const lastName = row.lastName.trim();
    if (!firstName && !lastName) return;
    if (!firstName || !lastName) {
      incompleteIndices.push(index);
      return;
    }
    names.push({ first_name: firstName, last_name: lastName });
  });
  return { names, incompleteIndices };
}

export function bestMatchFor(extractedName, matches) {
  return matches
    .filter((match) => match.extracted_name === extractedName)
    .reduce((best, current) => (!best || current.score > best.score ? current : best), null);
}

export function parseSourceReference(reference) {
  const match = /^\[(S\d+)\]\s+(.+?)\s+·\s+(pages?\s+.+?)\s+·\s+(.+)$/.exec(reference.trim());
  if (!match) return { id: "Source", filename: reference, location: "Verified evidence" };
  return {
    id: match[1],
    filename: match[2],
    location: `${match[3]} · ${match[4]}`,
  };
}

export async function validatePdfFile(file, maxSizeBytes) {
  if (!file || file.size === 0) throw new Error("Choose a non-empty PDF file.");
  if (file.size > maxSizeBytes) {
    throw new Error(`The PDF exceeds the ${Math.round(maxSizeBytes / 1024 / 1024)} MB upload limit.`);
  }
  const header = new Uint8Array(await file.slice(0, 1024).arrayBuffer());
  const signature = new TextDecoder("latin1").decode(header);
  if (!signature.includes("%PDF-")) throw new Error("The selected file does not contain a valid PDF signature.");
  return file;
}
