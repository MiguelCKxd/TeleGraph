// Coordinates are relative to the centre of the fitted image. A pinch keeps
// the point between the fingers anchored while its distance changes.
function photoGestures(stage, image, swipe) {
  const pointers = new Map();
  let scale = 1, x = 0, y = 0, start, lastTap, dragged = false;
  const clamp = (n, limit) => Math.max(-limit, Math.min(limit, n));
  function draw() {
    x = clamp(x, Math.max(0, (image.offsetWidth * scale - stage.clientWidth) / 2));
    y = clamp(y, Math.max(0, (image.offsetHeight * scale - stage.clientHeight) / 2));
    image.style.transform = 'translate(' + x + 'px,' + y + 'px) scale(' + scale + ')';
  }
  function position() {
    const [a, b = a] = pointers.values();
    const rect = stage.getBoundingClientRect();
    return {x: (a.x + b.x - rect.left - rect.right) / 2,
      y: (a.y + b.y - rect.top - rect.bottom) / 2,
      distance: Math.hypot(a.x - b.x, a.y - b.y)};
  }
  function baseline() {
    if (pointers.size) start = {...position(), panX: x, panY: y, scale};
  }
  stage.classList.add('photo-stage');
  image.draggable = false;
  stage.addEventListener('pointerdown', event => {
    if (event.button !== 0 || pointers.size >= 2) return;
    if (!pointers.size) dragged = false;
    else { dragged = true; lastTap = null; }
    pointers.set(event.pointerId, {x: event.clientX, y: event.clientY});
    stage.setPointerCapture(event.pointerId);
    baseline();
  });
  stage.addEventListener('pointermove', event => {
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
  });
  function end(event) {
    if (!pointers.has(event.pointerId)) return;
    const p = position(), dx = p.x - start.x, dy = p.y - start.y;
    pointers.delete(event.pointerId);
    if (event.type !== 'pointerup') { dragged = true; lastTap = null; }
    if (pointers.size) { baseline(); return; }
    if (event.type !== 'pointerup') return;
    if (!dragged) {
      const now = performance.now();
      if (lastTap && now - lastTap.time < 350 && Math.hypot(p.x-lastTap.x,p.y-lastTap.y) < 25) {
        const next = scale > 1 ? 1 : 2.5;
        x = p.x - (p.x - x) * next / scale;
        y = p.y - (p.y - y) * next / scale;
        scale = next; draw(); lastTap = null;
      } else lastTap = {...p, time: now};
    } else if (swipe && start.distance === 0 && scale === 1 && !hadPinch && Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.5) {
      swipe(dx < 0);
    }
  }
  let hadPinch = false;
  stage.addEventListener('pointerdown', () => { hadPinch = pointers.size > 1; });
  for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) stage.addEventListener(type, end);
}
