'use strict';

// Telegram stores the VP9 mask as BlockAdditional 1, a monochrome VP9 stream.
// A plain WebKit video can discard that stream. Read both streams locally.
function webmAlphaFrames(buffer) {
  const data = new Uint8Array(buffer);
  const view = new DataView(buffer);
  function vint(offset, end, marker = false) {
    let bit = 128, width = 1;
    while (bit && !(data[offset] & bit)) { bit >>= 1; width++; }
    if (!bit || offset + width > end || (marker && width > 4)) throw Error('Invalid WebM integer');
    let value = marker ? data[offset] : data[offset] & (bit - 1);
    for (let i = 1; i < width; i++) value = value * 256 + data[offset + i];
    const unknown = !marker && value === 2 ** (width * 7) - 1;
    return {value, next: offset + width, unknown};
  }
  function* elements(start, end) {
    while (start < end) {
      const id = vint(start, end, true);
      const size = vint(id.next, end);
      const stop = size.unknown && id.value === 0x18538067 ? end : size.next + size.value;
      if (!Number.isSafeInteger(stop) || stop > end || stop < size.next) throw Error('Invalid WebM element');
      yield {id: id.value, start: size.next, end: stop};
      start = stop;
    }
  }
  const children = (element) => element ? [...elements(element.start, element.end)] : [];
  const child = (element, id) => children(element).find(item => item.id === id);
  const uint = (element, fallback) => {
    if (!element) return fallback;
    if (element.end - element.start > 6) throw Error('Invalid WebM value');
    let value = 0;
    for (let i = element.start; i < element.end; i++) value = value * 256 + data[i];
    return value;
  };
  const bytes = (element) => data.subarray(element.start, element.end);
  const segment = [...elements(0, data.length)].find(item => item.id === 0x18538067);
  const scale = uint(child(child(segment, 0x1549a966), 0x2ad7b1), 1000000);
  const track = children(child(segment, 0x1654ae6b)).find(item =>
    item.id === 0xae && uint(child(item, 0x83)) === 1);
  const codec = child(track, 0x86);
  if (!codec || new TextDecoder().decode(bytes(codec)) !== 'V_VP9') return null;
  const number = uint(child(track, 0xd7));
  const video = child(track, 0xe0);
  const width = uint(child(video, 0xb0)), height = uint(child(video, 0xba));
  if (!width || !height || width > 512 || height > 512) return null;
  const frames = [];
  for (const cluster of children(segment)) {
    if (cluster.id !== 0x1f43b675) continue;
    const base = uint(child(cluster, 0xe7), 0);
    for (const group of children(cluster)) {
      if (group.id !== 0xa0) continue;
      const block = child(group, 0xa1);
      if (!block) continue;
      const trackNumber = vint(block.start, block.end);
      if (trackNumber.value !== number) continue;
      if (trackNumber.next + 3 >= block.end || data[trackNumber.next + 2] & 6) throw Error('Unsupported WebM block');
      const more = children(child(group, 0x75a1)).find(item =>
        item.id === 0xa6 && uint(child(item, 0xee), 1) === 1);
      const mask = child(more, 0xa5);
      if (!mask) continue;
      const timestamp = Math.round((base + view.getInt16(trackNumber.next)) * scale / 1000);
      frames.push({timestamp, color: data.subarray(trackNumber.next + 3, block.end), alpha: bytes(mask)});
      if (frames.length > 120) return null;
    }
  }
  if (frames.length) return {width, height, frames};
  return uint(child(video, 0x53c0), 0) === 0 ? {opaque: true} : null;

}

// Decode both VP9 streams through WebCodecs, then pair them by timestamp.
// The mask is the raw Y plane, avoiding any colour or range conversion.
async function decodeWebmAlpha(buffer, maxSide = 128) {
  const parsed = webmAlphaFrames(buffer);
  if (!parsed || parsed.opaque) return parsed;
  if (typeof VideoDecoder !== 'function') return null;
  const {width, height, frames} = parsed;
  const ratio = Math.min(1, maxSide / Math.max(width, height));
  const targetWidth = Math.max(1, Math.round(width * ratio));
  const targetHeight = Math.max(1, Math.round(height * ratio));
  const canvas = document.createElement('canvas');
  canvas.width = targetWidth; canvas.height = targetHeight;
  const context = canvas.getContext('2d', {willReadFrequently: true});
  const pictures = new Map(), masks = new Map(), copies = [];
  let failure = null;
  const makeDecoder = (output) => new VideoDecoder({output, error: error => { failure = error; }});
  const colorDecoder = makeDecoder(frame => {
    try {
      context.clearRect(0, 0, targetWidth, targetHeight);
      context.drawImage(frame, 0, 0, targetWidth, targetHeight);
      pictures.set(frame.timestamp, context.getImageData(0, 0, targetWidth, targetHeight));
    } catch (error) { failure = error; }
    finally { frame.close(); }
  });
  const alphaDecoder = makeDecoder(frame => {
    const copy = async () => {
      try {
        const rect = frame.visibleRect;
        if (!['I420', 'I420A', 'I422', 'I444', 'NV12'].includes(frame.format) || rect.width > 512 || rect.height > 512) {
          throw Error('Unsupported WebM alpha plane');
        }
        const bytes = new Uint8Array(frame.allocationSize());
        const [plane] = await frame.copyTo(bytes);
        const alpha = new Uint8Array(targetWidth * targetHeight);
        for (let y = 0; y < targetHeight; y++) {
          const row = plane.offset + Math.floor(y * rect.height / targetHeight) * plane.stride;
          for (let x = 0; x < targetWidth; x++) {
            alpha[y * targetWidth + x] = bytes[row + Math.floor(x * rect.width / targetWidth)];
          }
        }
        masks.set(frame.timestamp, alpha);
      } catch (error) { failure = error; }
      finally { frame.close(); }
    };
    copies.push(copy());
  });
  try {
    const config = {codec: 'vp09.00.10.08', codedWidth: width, codedHeight: height};
    if (!(await VideoDecoder.isConfigSupported(config)).supported) return null;
    colorDecoder.configure(config);
    alphaDecoder.configure(config);
    const chunk = (data, timestamp) => new EncodedVideoChunk({
      data, timestamp, type: data[0] & 0x0c ? 'delta' : 'key',
    });
    for (const frame of frames) {
      colorDecoder.decode(chunk(frame.color, frame.timestamp));
      alphaDecoder.decode(chunk(frame.alpha, frame.timestamp));
    }
    await Promise.all([colorDecoder.flush(), alphaDecoder.flush()]);
    await Promise.all(copies);
    if (failure) throw failure;
    const images = frames.map(({timestamp}) => {
      const image = pictures.get(timestamp), alpha = masks.get(timestamp);
      if (!image || !alpha) throw Error('Incomplete WebM animation');
      for (let i = 0; i < alpha.length; i++) image.data[i * 4 + 3] = alpha[i];
      return image;
    });
    const timeline = frames.map(({timestamp}, index) => ({timestamp, image: images[index]}))
      .sort((a, b) => a.timestamp - b.timestamp);
    return {width: targetWidth, height: targetHeight, frames: timeline.map(frame => frame.image),
      times: timeline.map(frame => (frame.timestamp - timeline[0].timestamp) / 1000)};
  } finally {
    if (colorDecoder.state !== 'closed') colorDecoder.close();
    if (alphaDecoder.state !== 'closed') alphaDecoder.close();
  }
}
