// Follow the visible WebView area without rebuilding the conversation or moving focus.
// visualViewport coordinates are CSS pixels in the layout viewport (also used by native glass).
(() => {
  const html = document.documentElement, viewport = window.visualViewport;
  let frame = 0, previous = '', width = innerWidth, restingHeight = innerHeight, keyboard = false;
  const editable = node => node?.matches?.('textarea, input:not([type=button]):not([type=checkbox]):not([type=radio]):not([type=range]):not([type=color]), [contenteditable=true]');
  const pixels = value => Math.round(value * 100) / 100;
  function update() {
    frame = 0;
    const zoomed = viewport && Math.abs(viewport.scale - 1) > .02;
    const height = pixels(!zoomed && viewport?.height > 0 ? viewport.height : innerHeight);
    const top = pixels(!zoomed ? Math.max(0, viewport?.offsetTop || 0) : 0);
    const currentWidth = pixels(innerWidth);
    if (Math.abs(currentWidth - width) > 2) {
      // Rotation/split view is a new baseline, not evidence of a keyboard.
      width = currentWidth; restingHeight = innerHeight; keyboard = false;
    }
    const editing = editable(document.activeElement);
    restingHeight = Math.max(restingHeight, innerHeight, height);
    keyboard = !zoomed && !!(editing || keyboard) && restingHeight - height > Math.max(100, restingHeight * .18);
    if (!editing && !keyboard) restingHeight = Math.max(height, innerHeight);
    const signature = [height, top, keyboard].join(':');
    if (signature === previous) return;
    previous = signature;
    const conversation = document.getElementById('scroll');
    const scrollTop = conversation?.scrollTop || 0;
    const atEnd = conversation && conversation.scrollHeight - conversation.clientHeight - scrollTop <= 4;
    html.style.setProperty('--viewport-height', height + 'px');
    html.style.setProperty('--viewport-top', top + 'px');
    html.toggleAttribute('data-keyboard', keyboard);
    // Keep the last message above the keyboard, or retain the user's older-message position.
    if (conversation) conversation.scrollTop = atEnd ? conversation.scrollHeight : scrollTop;
  }
  function schedule() { if (!frame) frame = requestAnimationFrame(update); }
  viewport?.addEventListener('resize', schedule, {passive: true});
  viewport?.addEventListener('scroll', schedule, {passive: true});
  window.addEventListener('resize', schedule, {passive: true});
  document.addEventListener('focusin', schedule);
  document.addEventListener('focusout', schedule);
  window.addEventListener('pageshow', schedule);
  update();
})();
