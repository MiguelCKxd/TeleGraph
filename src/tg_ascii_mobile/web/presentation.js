// User-facing appearance options. Defaults preserve the existing interface.
(() => {
  const labels = ['Estilo de controles', 'Entre corchetes', 'Sin corchetes', 'Iconos', 'Navegación', 'Menú',
    'Pestañas inferiores', 'Alineación de cabecera', 'Izquierda', 'Centrada', 'Separadores de chats',
    'Discontinuos', 'Continuos', 'Ninguno', 'Color de títulos', 'Color secundario', 'Color de paneles',
    'Color de separadores', 'Color de contadores', 'Color de controles', 'Decoración de títulos y menús', 'Altura mínima de chats (px)', 'Tamaño de fotos en la lista (px)',
    'Margen de separadores (px)', 'Grosor de títulos', 'Ancho máximo de burbujas (%)', 'Acción de cabecera', 'Nuevo chat',
    'Tamaño de mensajes (px)', 'Tamaño de cabecera (px)', 'Tamaño de nombres (px)', 'Tamaño de previsualización (px)',
    'Tamaño de metadatos (px)', 'Interlineado de mensajes (%)', 'Separación entre mensajes (px)',
    'Relleno horizontal de mensajes (px)', 'Relleno vertical de mensajes (px)', 'Altura mínima de botones (px)',
    'Líneas de previsualización', 'Alineación de burbujas', 'Fotos en la lista de chats', 'Horas en la lista de chats',
    'Contadores en la lista de chats', 'Texto de mensajes recibidos', 'Texto de mensajes enviados',
    'Metadatos de mensajes recibidos', 'Metadatos de mensajes enviados'];
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
    html.toggleAttribute('data-hide-list-avatars', p.list_avatars === false);
    html.toggleAttribute('data-hide-list-times', p.list_times === false);
    html.toggleAttribute('data-hide-list-badges', p.list_badges === false);
    html.toggleAttribute('data-message-gap', !!p.message_gap);
    html.toggleAttribute('data-preview-lines', Number(p.preview_lines || 1) > 1);
    html.dataset.bubbleAlignment = p.bubble_alignment || 'direction';
    for (const [key, variable] of [['title_color','--ui-title'], ['secondary_color','--ui-secondary'],
      ['panel_color','--ui-panel'], ['separator_color','--ui-line'], ['badge_color','--ui-badge'], ['control_color','--ui-control']]) {
      if (p[key]) style.setProperty(variable, p[key]); else style.removeProperty(variable);
    }
    for (const [key, variable] of [['row_height','--ui-row-height'], ['avatar_size','--ui-avatar-size'], ['separator_inset','--ui-separator-inset']]) {
      if (p[key]) style.setProperty(variable, p[key] + 'px'); else style.removeProperty(variable);
    }
    for (const [key, variable] of [['message_font_size','--ui-message-font'], ['header_font_size','--ui-header-font'],
      ['name_font_size','--ui-name-font'], ['preview_font_size','--ui-preview-font'], ['metadata_font_size','--ui-metadata-font'],
      ['message_gap','--ui-message-gap'], ['message_padding_x','--ui-message-padding-x'], ['message_padding_y','--ui-message-padding-y']]) {
      if (p[key]) style.setProperty(variable, p[key] + 'px'); else style.removeProperty(variable);
    }
    for (const [key, variable, attribute] of [
      ['incoming_text_color','--ui-incoming-text','data-incoming-text'],
      ['outgoing_text_color','--ui-outgoing-text','data-outgoing-text'],
      ['incoming_metadata_color','--ui-incoming-metadata','data-incoming-metadata'],
      ['outgoing_metadata_color','--ui-outgoing-metadata','data-outgoing-metadata']]) {
      html.toggleAttribute(attribute, !!p[key]);
      if (p[key]) style.setProperty(variable, p[key]); else style.removeProperty(variable);
    }
    if (p.message_line_height) style.setProperty('--ui-message-line-height', p.message_line_height / 100);
    else style.removeProperty('--ui-message-line-height');
    style.setProperty('--ui-button-height', (p.button_height || 44) + 'px');
    style.setProperty('--ui-preview-lines', p.preview_lines || 1);
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
      h('button', {type:'button', 'data-ui-icon':key, 'aria-label':t(label), 'aria-current':mode === key ? 'page' : null, onclick: action},
        h('span', {'aria-hidden':'true', html:icon(key)}), h('span', {}, t(label)))));
    (root.querySelector('.pane.side') || root).append(navigation);
  }
  function preview() {
    const message = (out, text) => h('article', {class: 'msg' + (out ? ' out' : '')},
      h('div', {class:'head'}, h('span', {class:'who'}, t(out ? 'Tú' : 'Ejemplo'))),
      h('div', {class:'text'}, t(text)),
      h('div', {class:'meta message-footer'}, h('time', {class:'bubble-clock'}, out ? '12:46' : '12:45'), out ? '✓✓' : ''));
    return h('div', {class:'presentation-preview', 'aria-label':t('Vista previa del aspecto')},
      h('div', {class:'bar'}, h('div', {class:'title'}, t('Conversación de ejemplo'))),
      h('div', {class:'presentation-preview-list'}, h('div', {class:'row'},
        h('span', {class:'avatar', 'aria-hidden':'true'}, h('span', {}, 'AB')),
        h('div', {class:'body'}, h('div', {class:'top'}, h('span', {class:'name'}, t('Conversación de ejemplo')), h('span', {class:'when'}, '12:45')),
          h('div', {class:'bottom'}, h('span', {class:'preview'}, t('Esta previsualización permite comprobar el tamaño y las líneas antes de volver a tus chats.')),
            h('span', {class:'badge'}, '3'))))),
      h('div', {class:'messages bubbles'}, message(false, 'Así se verá un mensaje recibido con tus ajustes.'),
        message(true, 'Y así se verá tu respuesta.')));
  }
  let groupsContext = '', openGroups = new Set(['preview', 'type']);
  function settings() {
    const p = options(), context = state.account + ':' + state.accountRevision;
    if (groupsContext !== context) {groupsContext = context; openGroups = new Set(['preview', 'type']);}
    const save = value => {
      const focused = document.activeElement, field = focused?.closest('[data-presentation-key]');
      const key = field?.dataset.presentationKey, tag = focused?.tagName.toLowerCase(), type = focused?.type;
      return saveLook(current => ({presentation:{...current.presentation, ...value}})).then(() => {
        // Keyboard users can keep stepping a slider after the common settings
        // renderer replaces the controls. Never steal focus from another input.
        if (!key || state.account + ':' + state.accountRevision !== context || document.activeElement !== document.body) return;
        const target = root.querySelector('[data-presentation-key="' + key + '"] ' + tag + (type ? '[type="' + type + '"]' : ''));
        target?.focus({preventScroll:true});
      });
    };
    const group = (key, label, ...children) => h('details', {class:'presentation-group', open:!!state.settingsQuery || openGroups.has(key),
      ontoggle:event => {if (event.currentTarget.open) openGroups.add(key); else openGroups.delete(key);}},
      h('summary', {}, t(label)), ...children);
    const choose = (key, label, values, initial) => h('label', {class:'setting', 'data-presentation-key':key}, h('span', {}, t(label)),
      h('select', {'aria-label':t(label), onchange:event => save({[key]:event.target.value})}, values.map(([value,name]) =>
        h('option', {value, selected:(p[key] ?? initial) === value}, t(name)))));
    const number = (key, label, initial, min, max, nonzeroMin = min) => h('div', {class:'setting number-setting', 'data-presentation-key':key}, h('span', {}, t(label)),
      numericSlider(t(label), p[key] ?? initial, min, max, value => save({[key]:value && value < nonzeroMin ? nonzeroMin : value})));
    const fallbackColor = variable => {
      const computed = getComputedStyle(document.documentElement);
      const value = (computed.getPropertyValue(variable).trim() || computed.getPropertyValue('--text').trim());
      return /^#[0-9a-f]{3}$/i.test(value) ? '#' + [...value.slice(1)].map(letter => letter + letter).join('')
        : /^#[0-9a-f]{6}$/i.test(value) ? value : '#808080';
    };
    const color = (key, label, fallback) => h('div', {class:'setting', 'data-presentation-key':key}, h('span', {}, t(label)),
      h('input', {type:'color', 'aria-label':t(label), value:p[key] || fallbackColor(fallback), onchange:event => save({[key]:event.target.value})}),
      p[key] ? button(t('Restablecer'), () => save({[key]:''})) : null);
    const toggle = (key, label) => h('div', {'data-presentation-key':key},
      switchSetting(t(label), p[key] !== false, () => save({[key]:p[key] === false})));
    return h('div', {class:'section presentation-settings'}, h('h4', {}, t('Composición de la interfaz')),
      group('preview','Vista previa', preview()),
      group('type','Texto y legibilidad',
        h('p', {class:'muted small'}, t('Cero hereda el tamaño general. Los tamaños independientes no cambian la fuente elegida.')),
        number('message_font_size','Tamaño de mensajes (px)',0,0,72,8),
        number('header_font_size','Tamaño de cabecera (px)',0,0,72,8),
        number('name_font_size','Tamaño de nombres (px)',0,0,64,8),
        number('preview_font_size','Tamaño de previsualización (px)',0,0,48,8),
        number('metadata_font_size','Tamaño de metadatos (px)',0,0,40,8),
        number('message_line_height','Interlineado de mensajes (%)',0,0,240,100),
        number('title_weight','Grosor de títulos',700,400,800)),
      group('navigation','Navegación y controles',
        choose('controls','Estilo de controles',[['brackets','Entre corchetes'],['plain','Sin corchetes'],['icons','Iconos']], 'brackets'),
        choose('navigation','Navegación',[['menu','Menú'],['tabs','Pestañas inferiores']], 'menu'),
        h('label', {class:'setting', 'data-presentation-key':'list_title'}, h('span', {}, t('Título de la lista de chats')),
          h('input', {type:'text', maxlength:80, 'aria-label':t('Título de la lista de chats'), value:p.list_title || '',
            placeholder:state.settings.app_display_name || 'TeleGraph', onchange:event => save({list_title:event.target.value})})),
        choose('primary_action','Acción de cabecera',[['menu','Menú'],['compose','Nuevo chat']], 'menu'),
        choose('header_alignment','Alineación de cabecera',[['left','Izquierda'],['center','Centrada']], 'left'),
        number('button_height','Altura mínima de botones (px)',44,44,80),
        toggle('show_online','Mostrar estado en línea de la conexión'), toggle('text_decoration','Decoración de títulos y menús')),
      group('list','Lista de chats',
        number('row_height','Altura mínima de chats (px)',0,0,160), number('avatar_size','Tamaño de fotos en la lista (px)',0,0,96),
        number('preview_lines','Líneas de previsualización',1,1,4),
        choose('separators','Separadores de chats',[['dashed','Discontinuos'],['solid','Continuos'],['none','Ninguno']], 'dashed'),
        number('separator_inset','Margen de separadores (px)',0,0,160),
        toggle('list_avatars','Fotos en la lista de chats'), toggle('list_times','Horas en la lista de chats'),
        toggle('list_badges','Contadores en la lista de chats')),
      group('messages','Mensajes y burbujas',
        choose('bubble_alignment','Alineación de burbujas', [['direction','Según remitente'], ['start','Todas al inicio'],
          ['end','Todas al final'], ['center','Centradas']], 'direction'),
        number('bubble_width','Ancho máximo de burbujas (%)',88,50,100),
        number('message_gap','Separación entre mensajes (px)',0,0,48),
        number('message_padding_x','Relleno horizontal de mensajes (px)',0,0,40),
        number('message_padding_y','Relleno vertical de mensajes (px)',0,0,32),
        toggle('private_sender_names','Nombres de remitentes en chats privados'), toggle('bubble_border','Bordes de burbujas')),
      group('colors','Colores de interfaz y mensajes',
        color('title_color','Color de títulos','--strong'), color('secondary_color','Color secundario','--muted'),
        color('panel_color','Color de paneles','--panel'), color('separator_color','Color de separadores','--line'),
        color('badge_color','Color de contadores','--text'), color('control_color','Color de controles','--text'),
        color('incoming_text_color','Texto de mensajes recibidos','--bubble-in-ink'),
        color('outgoing_text_color','Texto de mensajes enviados','--bubble-out-ink'),
        color('incoming_metadata_color','Metadatos de mensajes recibidos','--muted'),
        color('outgoing_metadata_color','Metadatos de mensajes enviados','--muted'),
        h('p', {class:'muted small'}, t('Los fondos de las burbujas se cambian con los colores de Apariencia.'))),
      h('p', {class:'muted small'}, t('Cero mantiene el tamaño habitual. Estas opciones solo cambian el aspecto en este dispositivo.')),
      button(t('Restablecer composición'), () => saveLook({presentation:{}})));
  }
  window.tgPresentation = {apply, mount, settings, iconize, labels};
})();
