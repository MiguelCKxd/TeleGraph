// User-facing appearance options. Defaults preserve the existing interface.
(() => {
  const labels = ['Estilo de controles', 'Entre corchetes', 'Sin corchetes', 'Iconos', 'Navegación', 'Menú',
    'Pestañas inferiores', 'Alineación de cabecera', 'Izquierda', 'Centrada', 'Separadores de chats',
    'Discontinuos', 'Continuos', 'Ninguno', 'Color de títulos', 'Color secundario', 'Color de paneles',
    'Color de separadores', 'Color de contadores', 'Color de controles', 'Decoración de títulos y menús', 'Altura mínima de chats (px)', 'Tamaño de fotos en la lista (px)',
    'Margen de separadores (px)', 'Grosor de títulos', 'Ancho máximo de burbujas (%)', 'Acción de cabecera', 'Nuevo chat'];
  const paths = {
    '<': '<path d="m15 5-7 7 7 7"/>',
    '≡': '<path d="M5 6h14M5 12h14M5 18h14"/>',
    '⋯': '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
    '+': '<path d="m9 17 8-8a3 3 0 0 0-4-4L5 13a5 5 0 0 0 7 7l8-8"/>',
    'contacts': '<circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>',
    'chats': '<path d="M21 11a9 9 0 0 1-9 9H4l-3 2 1-7A9 9 0 1 1 21 11Z"/>',
    'settings': '<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="8" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="10" cy="18" r="2"/>',
    'calls': '<path d="m6 3 4 4-3 3a17 17 0 0 0 7 7l3-3 4 4-2 3C10 22 2 14 3 5Z"/>',
    '✎': '<path d="M13 4H5a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h13a2 2 0 0 0 2-2v-8M16 3l5 5M9 15l1-5 8-8 4 4-8 8Z"/>',
  };
  const icon = key => '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' + paths[key] + '</svg>';
  const options = () => state.appearance?.presentation || {};
  let headerFrame = 0;
  const headerSizes = new ResizeObserver(() => {
    if (!headerFrame) headerFrame = requestAnimationFrame(() => { headerFrame = 0; balanceHeaders(); });
  });
  function balanceHeaders() {
    const centered = options().header_alignment === 'center';
    const updates = [...root.querySelectorAll('.bar')].map(bar => {
      const children = [...bar.children], title = children.find(node => node.classList.contains('title'));
      if (!title) return null;
      const index = children.indexOf(title), gap = parseFloat(getComputedStyle(bar).columnGap) || 0;
      const width = nodes => nodes.reduce((total,node) => {
        const size = node.getBoundingClientRect().width;
        return total + (size ? size + gap : 0);
      }, 0);
      const difference = centered ? width(children.slice(index + 1)) - width(children.slice(0, index)) : 0;
      return {title, difference};
    });
    for (const entry of updates) if (entry) {
      entry.title.style.paddingInlineStart = entry.difference > 0 ? entry.difference + 'px' : '';
      entry.title.style.paddingInlineEnd = entry.difference < 0 ? -entry.difference + 'px' : '';
    }
  }
  function iconize(node, symbol) {
    if (!paths[symbol]) return node;
    node.dataset.uiIcon = symbol;
    const text = h('span', {class: 'control-text'}, node.textContent);
    node.replaceChildren(text, h('span', {class: 'control-icon', 'aria-hidden': 'true', html: icon(symbol)}));
    return node;
  }
  function apply() {
    const p = options(), html = document.documentElement, style = html.style;
    html.dataset.controls = p.controls || 'brackets';
    html.dataset.headerAlignment = p.header_alignment || 'left';
    html.dataset.separators = p.separators || 'dashed';
    html.toggleAttribute('data-hide-online', p.show_online === false);
    html.toggleAttribute('data-hide-private-senders', p.private_sender_names === false);
    html.toggleAttribute('data-no-bubble-border', p.bubble_border === false);
    html.toggleAttribute('data-plain-headings', p.text_decoration === false);
    for (const [key, variable] of [['title_color','--ui-title'], ['secondary_color','--ui-secondary'],
      ['panel_color','--ui-panel'], ['separator_color','--ui-line'], ['badge_color','--ui-badge'], ['control_color','--ui-control']]) {
      if (p[key]) style.setProperty(variable, p[key]); else style.removeProperty(variable);
    }
    for (const [key, variable] of [['row_height','--ui-row-height'], ['avatar_size','--ui-avatar-size'], ['separator_inset','--ui-separator-inset']]) {
      if (p[key]) style.setProperty(variable, p[key] + 'px'); else style.removeProperty(variable);
    }
    style.setProperty('--ui-title-weight', p.title_weight || 700);
    style.setProperty('--ui-bubble-width', (p.bubble_width || 88) + '%');
  }
  function mount() {
    const p = options();
    headerSizes.disconnect();
    if (p.header_alignment === 'center') for (const bar of root.querySelectorAll('.bar')) {
      headerSizes.observe(bar);
      for (const node of bar.children) if (!node.classList.contains('title')) headerSizes.observe(node);
    }
    balanceHeaders();
    root.toggleAttribute('data-private-chat', (state.view === 'chat' || WIDE()) && ['user', 'secret'].includes(state.open?.chat?.kind));
    root.querySelectorAll('.app-navigation').forEach(node => node.remove());
    if (p.navigation !== 'tabs' || state.locked || state.stage !== 'ready' || WINDOW_CHAT !== null) return;
    const mode = WIDE() ? listMode() : state.view;
    if (!['chats','contacts','settings','stories'].includes(mode)) return;
    const entries = [
      ['contacts', 'Contactos', () => go('contacts', {contacts:null, search:''})],
      ...(feature('call_history') ? [['calls', 'Calls', () => callsView(false)]] : []),
      ['chats', 'Chats', () => go('chats', {search:''})],
      ['settings', 'Ajustes', () => go('settings')],
    ];
    const navigation = h('nav', {class: 'app-navigation', 'aria-label': t('Navegación principal')}, entries.map(([key,label,action]) =>
      h('button', {type:'button', 'aria-label':t(label), 'aria-current':mode === key ? 'page' : null, onclick: action},
        h('span', {'aria-hidden':'true', html:icon(key)}), h('span', {}, t(label)))));
    (root.querySelector('.pane.side') || root).append(navigation);
  }
  function settings() {
    const p = options();
    const save = value => saveLook(current => ({presentation:{...current.presentation, ...value}}));
    const choose = (key, label, values, initial) => h('label', {class:'setting'}, h('span', {}, t(label)),
      h('select', {'aria-label':t(label), onchange:event => save({[key]:event.target.value})}, values.map(([value,name]) =>
        h('option', {value, selected:(p[key] ?? initial) === value}, t(name)))));
    const number = (key, label, initial, min, max) => h('div', {class:'setting'}, h('span', {}, t(label)),
      numericSlider(t(label), p[key] ?? initial, min, max, value => save({[key]:value})));
    const color = (key, label, fallback) => h('div', {class:'setting'}, h('span', {}, t(label)),
      h('input', {type:'color', 'aria-label':t(label), value:p[key] || getComputedStyle(document.documentElement).getPropertyValue(fallback).trim(), onchange:event => save({[key]:event.target.value})}),
      p[key] ? button(t('Restablecer'), () => save({[key]:''})) : null);
    return h('div', {class:'section presentation-settings'}, h('h4', {}, t('Composición de la interfaz')),
      choose('controls','Estilo de controles',[['brackets','Entre corchetes'],['plain','Sin corchetes'],['icons','Iconos']], 'brackets'),
      choose('navigation','Navegación',[['menu','Menú'],['tabs','Pestañas inferiores']], 'menu'),
      h('label', {class:'setting'}, h('span', {}, t('Título de la lista de chats')),
        h('input', {type:'text', maxlength:80, 'aria-label':t('Título de la lista de chats'), value:p.list_title || '',
          placeholder:state.settings.app_display_name || 'TeleGraph', onchange:event => save({list_title:event.target.value})})),
      choose('primary_action','Acción de cabecera',[['menu','Menú'],['compose','Nuevo chat']], 'menu'),
      choose('header_alignment','Alineación de cabecera',[['left','Izquierda'],['center','Centrada']], 'left'),
      choose('separators','Separadores de chats',[['dashed','Discontinuos'],['solid','Continuos'],['none','Ninguno']], 'dashed'),
      color('title_color','Color de títulos','--strong'), color('secondary_color','Color secundario','--muted'),
      color('panel_color','Color de paneles','--panel'), color('separator_color','Color de separadores','--line'),
      color('badge_color','Color de contadores','--text'),
      color('control_color','Color de controles','--text'),
      number('row_height','Altura mínima de chats (px)',0,0,160), number('avatar_size','Tamaño de fotos en la lista (px)',0,0,96),
      number('separator_inset','Margen de separadores (px)',0,0,160), number('title_weight','Grosor de títulos',700,400,800),
      number('bubble_width','Ancho máximo de burbujas (%)',88,50,100),
      switchSetting(t('Mostrar estado en línea de la conexión'), p.show_online !== false, () => save({show_online:p.show_online === false})),
      switchSetting(t('Nombres de remitentes en chats privados'), p.private_sender_names !== false, () => save({private_sender_names:p.private_sender_names === false})),
      switchSetting(t('Bordes de burbujas'), p.bubble_border !== false, () => save({bubble_border:p.bubble_border === false})),
      switchSetting(t('Decoración de títulos y menús'), p.text_decoration !== false, () => save({text_decoration:p.text_decoration === false})),
      h('p', {class:'muted small'}, t('Cero mantiene el tamaño habitual. Estas opciones solo cambian el aspecto en este dispositivo.')),
      button(t('Restablecer composición'), () => saveLook({presentation:{}})));
  }
  window.tgPresentation = {apply, mount, settings, iconize, labels};
})();
