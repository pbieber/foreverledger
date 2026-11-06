// A small MP4 writer for one H.264 video track, so exports need no library. The index
// comes before the video data, so editors and players can open the file straight away.

const ascii = (text) => Uint8Array.from(text, (ch) => ch.charCodeAt(0));
const u8 = (...values) => Uint8Array.from(values);

function u16(value) {
  return u8((value >>> 8) & 255, value & 255);
}

function u32(value) {
  return u8((value >>> 24) & 255, (value >>> 16) & 255, (value >>> 8) & 255, value & 255);
}

const zeros = (count) => new Uint8Array(count);

function join(parts) {
  const out = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0));
  let at = 0;
  for (const part of parts) {
    out.set(part, at);
    at += part.length;
  }
  return out;
}

function box(type, ...parts) {
  const body = join(parts);
  return join([u32(body.length + 8), ascii(type), body]);
}

const fullBox = (type, version, flags, ...parts) => box(type, u32(((version & 255) * 2 ** 24) + flags), ...parts);

const MATRIX = join([u32(0x00010000), zeros(12), u32(0x00010000), zeros(12), u32(0x40000000)]);

// Chrome names colours in words; MP4 uses the standard's numbers.
const COLOUR_PRIMARIES = { bt709: 1, bt470bg: 5, smpte170m: 6 };
const COLOUR_TRANSFER = { bt709: 1, smpte170m: 6 };
const COLOUR_MATRIX = { rgb: 0, bt709: 1, bt470bg: 5, smpte170m: 6 };

function colourBox(colour) {
  const primaries = COLOUR_PRIMARIES[colour?.primaries];
  const transfer = COLOUR_TRANSFER[colour?.transfer];
  const matrix = COLOUR_MATRIX[colour?.matrix];
  if (primaries === undefined || transfer === undefined || matrix === undefined) return new Uint8Array(0);
  return box("colr", ascii("nclx"), u16(primaries), u16(transfer), u16(matrix), u8(colour.fullRange ? 0x80 : 0));
}

function sampleEntry({ width, height, description, colour }) {
  return box("avc1",
    zeros(6), u16(1), // Reserved, then which data reference to use.
    zeros(16), u16(width), u16(height),
    u32(0x00480000), u32(0x00480000), zeros(4), u16(1), // 72 dpi, one frame per sample.
    zeros(32), u16(0x0018), u16(0xffff), // No compressor name, 24 bit colour.
    box("avcC", description),
    colourBox(colour));
}

function movie(options, chunkOffset) {
  const { width, height, timescale, frameDuration, samples } = options;
  const duration = samples.length * frameDuration;
  const keyFrames = samples.flatMap((sample, i) => (sample.key ? [u32(i + 1)] : []));
  const sampleTable = box("stbl",
    fullBox("stsd", 0, 0, u32(1), sampleEntry(options)),
    fullBox("stts", 0, 0, u32(1), u32(samples.length), u32(frameDuration)),
    fullBox("stss", 0, 0, u32(keyFrames.length), ...keyFrames),
    fullBox("stsc", 0, 0, u32(1), u32(1), u32(samples.length), u32(1)),
    fullBox("stsz", 0, 0, u32(0), u32(samples.length), ...samples.map((sample) => u32(sample.data.length))),
    fullBox("stco", 0, 0, u32(1), u32(chunkOffset)));
  return box("moov",
    fullBox("mvhd", 0, 0, zeros(8), u32(timescale), u32(duration), u32(0x00010000), u16(0x0100), zeros(10), MATRIX, zeros(24), u32(2)),
    box("trak",
      fullBox("tkhd", 0, 3, zeros(8), u32(1), zeros(4), u32(duration), zeros(8), zeros(4), zeros(4), MATRIX, u32(width * 65536), u32(height * 65536)),
      box("mdia",
        fullBox("mdhd", 0, 0, zeros(8), u32(timescale), u32(duration), u16(0x55c4), zeros(2)),
        fullBox("hdlr", 0, 0, zeros(4), ascii("vide"), zeros(12), ascii("VideoHandler"), zeros(1)),
        box("minf",
          fullBox("vmhd", 0, 1, zeros(8)),
          box("dinf", fullBox("dref", 0, 0, u32(1), fullBox("url ", 0, 1))),
          sampleTable))));
}

// samples: [{data: Uint8Array, key: boolean}] in playing order, all the same length of time.
// description: the encoder's H.264 setup record. colour: optional, as Chrome reports it.
export function writeMp4(options) {
  const { samples } = options;
  if (!samples.length) throw new Error("The video has no frames");
  if (!samples[0].key) throw new Error("The video must start on a key frame");
  const header = box("ftyp", ascii("isom"), u32(512), ascii("isom"), ascii("iso2"), ascii("avc1"), ascii("mp41"));
  const dataSize = samples.reduce((sum, sample) => sum + sample.data.length, 0);
  if (dataSize + 8 >= 2 ** 32) throw new Error("The video is too large");
  const indexSize = movie(options, 0).length;
  const firstSample = header.length + indexSize + 8;
  return join([header, movie(options, firstSample), u32(dataSize + 8), ascii("mdat"), ...samples.map((sample) => sample.data)]);
}
