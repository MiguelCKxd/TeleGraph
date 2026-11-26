// Native SwiftUI navigation controls. With the feature off, no DOM observers,
// polling, native view updates or glass resources are kept running.
(() => {
  const bridge = window.webkit?.messageHandlers?.tgNativeGlass;
  if (!bridge) return;
  const session = [...crypto.getRandomValues(new Uint8Array(16))].map(value => value.toString(16).padStart(2, '0')).join('');
  const nodes = new Map(), metadata = new WeakMap(), watchedBars = new Set();
  let serial = 0, revision = 0, frame = 0, observing = false, lastPayload = '';
  const active = () => state.settings?.advanced_features?.native_liquid_glass === true &&
    state.stage === 'ready' && !state.locked && !unavailableWindow() && !document.hidden &&
    !document.querySelector('dialog[open]') && document.getElementById('sheet-layer').hidden &&
    document.getElementById('call-layer').hidden && document.getElementById('group-call-layer').hidden;
  const restore = node => {
    const saved = metadata.get(node);
    if (!saved?.mirrored) return;
    node.classList.remove('native-glass-control');
    for (const [name, value] of [['aria-hidden', saved.aria], ['tabindex', saved.tab]]) {
      if (value === null) node.removeAttribute(name); else node.setAttribute(name, value);
    }
    saved.mirrored = false;
  };
  const clear = () => { for (const node of nodes.values()) restore(node); nodes.clear(); };
  const schedule = () => { if (!frame) frame = requestAnimationFrame(() => { frame = 0; refresh(); }); };
  const mutations = new MutationObserver(changes => {
    const toolbar = node => node.nodeType === 1 && (node.matches('.bar, .winbar, dialog') || node.querySelector('.bar, .winbar, dialog'));
    if (changes.some(change => change.target.closest?.('.bar, .winbar') || change.target.parentElement?.closest('.bar, .winbar') ||
        ['sheet-layer', 'call-layer', 'group-call-layer'].includes(change.target.id) ||
        [...change.addedNodes, ...change.removedNodes].some(toolbar))) schedule();
  }), sizes = new ResizeObserver(schedule);
  function observe(enabled) {
    if (enabled === observing) return;
    observing = enabled;
    if (enabled) {
      mutations.observe(document.getElementById('app'), {subtree: true, childList: true, characterData: true,
        attributes: true, attributeFilter: ['disabled', 'aria-label', 'title', 'hidden']});
      for (const id of ['sheet-layer', 'call-layer', 'group-call-layer'])
        mutations.observe(document.getElementById(id), {attributes: true, attributeFilter: ['hidden']});
      mutations.observe(document.body, {childList: true});
      document.addEventListener('close', schedule, true);
      document.addEventListener('toggle', schedule, true);
      window.addEventListener('resize', schedule);
      window.visualViewport?.addEventListener('resize', schedule);
    } else {
      mutations.disconnect(); sizes.disconnect(); watchedBars.clear();
      document.removeEventListener('close', schedule, true);
      document.removeEventListener('toggle', schedule, true);
      window.removeEventListener('resize', schedule);
      window.visualViewport?.removeEventListener('resize', schedule);
    }
  }
  function refresh() {
    if (typeof state === 'undefined') return;
    const enabled = state.settings?.advanced_features?.native_liquid_glass === true;
    observe(enabled);
    if (!active()) {
      clear();
      if (lastPayload !== 'disabled') bridge.postMessage({session, enabled: false, revision: ++revision, controls: []});
      lastPayload = 'disabled'; return;
    }
    const controls = [], live = new Set();
    const bars = new Set(document.querySelectorAll('#app .bar, #app .winbar'));
    for (const bar of watchedBars) if (!bars.has(bar)) { sizes.unobserve(bar); watchedBars.delete(bar); }
    // Only fixed navigation bars. Mirroring buttons inside a web scroll area
    // would intercept its pan gesture and break ordinary scrolling.
    for (const bar of bars) {
      if (!watchedBars.has(bar)) { sizes.observe(bar); watchedBars.add(bar); }
      for (const node of bar.querySelectorAll(':scope > button:not(.title):not(.peer-control)')) {
        const rect = node.getBoundingClientRect(), style = getComputedStyle(node);
        if (node.hidden || rect.width < 28 || rect.height < 28 || rect.top < 0 || rect.bottom > innerHeight ||
            rect.left < 0 || rect.right > innerWidth || style.visibility === 'hidden' || controls.length >= 24) continue;
        let data = metadata.get(node);
        if (!data) { data = {id: ++serial, aria: node.getAttribute('aria-hidden'), tab: node.getAttribute('tabindex')}; metadata.set(node, data); }
        live.add(data.id); nodes.set(data.id, node);
        const label = (node.getAttribute('aria-label') || node.title || node.textContent).trim().slice(0, 160);
        const text = node.textContent.trim().slice(0, 40);
        const symbols = {'<': 'chevron.left', '›': 'chevron.right', '⋯': 'ellipsis', '≡': 'line.3.horizontal',
          'x': 'xmark', '⧉': 'square.on.square', '🔒': 'lock'};
        controls.push({id: data.id, label, text, symbol: node.id === 'connection-alert' ? 'wifi.exclamationmark' : symbols[node.dataset.uiIcon || text] || '',
          x: rect.x, y: rect.y, width: rect.width, height: rect.height, disabled: node.disabled,
          font: parseFloat(style.fontSize), family: style.fontFamily.split(',')[0].replace(/[\"']/g, '').trim(), radius: parseFloat(style.borderTopLeftRadius) || 0, color: style.color});
      }
    }
    for (const [id, node] of nodes) if (!live.has(id)) { restore(node); nodes.delete(id); }
    const payload = {enabled: true, controls, dark: document.documentElement.dataset.theme !== 'light',
      reduceMotion: !!state.settings?.reduce_animations || matchMedia('(prefers-reduced-motion: reduce)').matches};
    const encoded = JSON.stringify(payload);
    if (encoded === lastPayload) return;
    lastPayload = encoded;
    bridge.postMessage({...payload, session, revision: ++revision});
  }
  window.tgNativeGlass = {
    refresh,
    acknowledge(current, ids, owner) {
      if (current !== revision || owner !== session) return;
      const accepted = new Set(ids);
      for (const [id, node] of nodes) {
        if (!accepted.has(id) || !active()) { restore(node); continue; }
        const data = metadata.get(node);
        if (!data.mirrored) {
          data.aria = node.getAttribute('aria-hidden'); data.tab = node.getAttribute('tabindex'); data.mirrored = true;
          node.classList.add('native-glass-control'); node.setAttribute('aria-hidden', 'true'); node.setAttribute('tabindex', '-1');
        }
      }
    },
    activate(id, current, owner) {
      const node = nodes.get(id);
      if (owner === session && current === revision && active() && node?.isConnected && !node.disabled) node.click();
    },
    environment(voiceOver) {
      window.tgNativeAccessibility = {voiceOver};
      lastPayload = ''; refresh();
    },
  };
  document.addEventListener('visibilitychange', refresh);
})();
