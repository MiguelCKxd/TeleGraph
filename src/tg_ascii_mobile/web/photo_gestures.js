// Coordinates are relative to the centre of the fitted image. Layout is read
// when a gesture starts, never for every pointermove in a pinch.
function photoGestures(stage, image, swipe) {
  const pointers = new Map();
  let scale = 1, x = 0, y = 0, start, lastTap, bounds, frame = 0;
  let dragged = false, pinched = false;
  const clamp = (n, limit) => Math.max(-limit, Math.min(limit, n));
  function measure() {
    const rect = stage.getBoundingClientRect();
    bounds = {cx: (rect.left + rect.right) / 2, cy: (rect.top + rect.bottom) / 2,
      w: rect.width, h: rect.height, imageW: image.offsetWidth, imageH: image.offsetHeight};
  }
  function draw() {
    x = clamp(x, Math.max(0, (bounds.imageW * scale - bounds.w) / 2));
    y = clamp(y, Math.max(0, (bounds.imageH * scale - bounds.h) / 2));
    if (!frame) frame = requestAnimationFrame(() => {
      frame = 0;
      image.style.transform = 'translate3d(' + x + 'px,' + y + 'px,0) scale(' + scale + ')';
    });
  }
  function position() {
    const [a, b = a] = pointers.values();
    return {x: (a.x + b.x) / 2 - bounds.cx, y: (a.y + b.y) / 2 - bounds.cy,
      distance: Math.hypot(a.x - b.x, a.y - b.y)};
  }
  function baseline() {
    start = {...position(), panX: x, panY: y, scale};
  }
  function move(event) {
    if (!pointers.has(event.pointerId)) return;
    pointers.set(event.pointerId, {x: event.clientX, y: event.clientY});
    const p = position(), dx = p.x - start.x, dy = p.y - start.y;
    if (Math.hypot(dx, dy) > 8) dragged = true;
    if (pointers.size === 2 && start.distance > 0) {
      scale = Math.max(1, Math.min(6, start.scale * p.distance / start.distance));
      const factor = scale / start.scale;
      x = p.x - (start.x - start.panX) * factor;
      y = p.y - (start.y - start.panY) * factor;
    } else { x = start.panX + dx; y = start.panY + dy; }
    draw();
  }
  function end(event) {
    if (!pointers.has(event.pointerId)) return;
    if (event.type === 'pointerup') move(event);
    else { pinched = true; lastTap = null; }
    const p = position(), dx = p.x - start.x, dy = p.y - start.y;
    pointers.delete(event.pointerId);
    if (pointers.size) { baseline(); return; }
    if (event.type !== 'pointerup' || pinched) return;
    if (!dragged) {
      const now = performance.now();
      if (lastTap && now - lastTap.time < 350 && Math.hypot(p.x-lastTap.x,p.y-lastTap.y) < 25) {
        const next = scale > 1 ? 1 : 2.5;
        x = p.x - (p.x - x) * next / scale;
        y = p.y - (p.y - y) * next / scale;
        scale = next; draw(); lastTap = null;
      } else lastTap = {...p, time: now};
    } else if (swipe && scale === 1 && Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.5) {
      swipe(dx < 0);
    }
  }
  stage.classList.add('photo-stage');
  image.draggable = false;
  const resized = () => {
    if (!stage.isConnected) return;
    measure(); draw();
    if (pointers.size) baseline();
  };
  image.addEventListener('load', resized);
  const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(resized) : null;
  observer?.observe(stage);
  observer?.observe(image);
  stage.addEventListener('pointerdown', event => {
    if (event.button !== 0 || pointers.size >= 2) return;
    if (!pointers.size) { measure(); dragged = pinched = false; }
    else { pinched = dragged = true; lastTap = null; }
    pointers.set(event.pointerId, {x: event.clientX, y: event.clientY});
    stage.setPointerCapture(event.pointerId);
    baseline();
  });
  stage.addEventListener('pointermove', move);
  for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) stage.addEventListener(type, end);
  return () => {
    observer?.disconnect();
    image.removeEventListener('load', resized);
    if (frame) cancelAnimationFrame(frame);
  };
}
