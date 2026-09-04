export function hasMatchingImageSignature(type: string, bytes: Uint8Array) {
  if (type === "image/png") {
    return bytes.length >= 8 && [137, 80, 78, 71, 13, 10, 26, 10]
      .every((value, index) => bytes[index] === value);
  }
  if (type === "image/jpeg") return bytes.length >= 3 && bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255;
  return type === "image/webp"
    && bytes.length >= 12
    && String.fromCharCode(...bytes.slice(0, 4)) === "RIFF"
    && String.fromCharCode(...bytes.slice(8, 12)) === "WEBP";
}

export function hasMatchingVideoSignature(type: string, bytes: Uint8Array) {
  if (type === "video/webm") {
    return bytes.length >= 4 && [0x1a, 0x45, 0xdf, 0xa3]
      .every((value, index) => bytes[index] === value);
  }
  return (type === "video/mp4" || type === "video/quicktime")
    && bytes.length >= 12
    && String.fromCharCode(...bytes.slice(4, 8)) === "ftyp";
}

export function hasMatchingAudioSignature(type: string, bytes: Uint8Array) {
  const ascii = (start: number, end: number) => String.fromCharCode(...bytes.slice(start, end));
  if (type === "audio/wav" || type === "audio/x-wav") {
    return bytes.length >= 12 && ascii(0, 4) === "RIFF" && ascii(8, 12) === "WAVE";
  }
  if (type === "audio/mpeg") {
    return bytes.length >= 3 && (
      ascii(0, 3) === "ID3"
      || (bytes[0] === 0xff && (bytes[1] & 0xe0) === 0xe0)
    );
  }
  if (type === "audio/mp4" || type === "audio/x-m4a") {
    return bytes.length >= 12 && ascii(4, 8) === "ftyp";
  }
  if (type === "audio/webm") {
    return bytes.length >= 4 && [0x1a, 0x45, 0xdf, 0xa3]
      .every((value, index) => bytes[index] === value);
  }
  return type === "audio/ogg" && bytes.length >= 4 && ascii(0, 4) === "OggS";
}
