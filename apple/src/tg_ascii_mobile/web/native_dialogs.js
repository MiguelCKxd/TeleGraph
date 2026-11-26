// Simple system dialogs are optional. Complex forms and rich reaction sheets
// retain their web implementation. Business actions stay in the original UI.
(() => {
  let pending = null;
  const enabled = () => typeof state !== 'undefined' && state.appearance?.native_dialogs === true &&
    ['iOS', 'Android'].includes(PLATFORM) && WINDOW_CHAT === null && state.stage === 'ready' && !state.locked &&
    !document.hidden && !document.querySelector('dialog[open]');
  const context = () => JSON.stringify([state.account, state.accountRevision, state.view,
    state.open?.peer, state.open?.thread?.root, state.open?.topic?.id, state.profile?.id]);
  const current = item => pending === item && enabled() && item.context === context();
  function cancel() {
    const item = pending;
    if (!item) return false;
    pending = null;
    api('native_dialog_cancel', {request_id: item.id, account: item.account}).catch(() => {});
    return true;
  }
  function start(request, action, fallback) {
    if (!enabled() || !document.getElementById('sheet-layer').hidden) return false;
    if (pending) return true; // Ignore a rapid second tap while presentation starts.
    const id = [...crypto.getRandomValues(new Uint8Array(16))].map(value => value.toString(16).padStart(2, '0')).join('');
    const item = {id, account: state.account, context: context()};
    pending = item;
    request = {...request, id, cancel: t('Cancelar'), reduce_motion: !!state.settings?.reduce_animations ||
      matchMedia('(prefers-reduced-motion: reduce)').matches};
    api('native_dialog', {request, account: item.account}).then(result => {
      if (!current(item)) return;
      pending = null;
      if (!result?.handled) { fallback(); return; }
      if (!result.cancelled) attempt(() => action(result));
    }).catch(() => {
      if (!current(item)) return;
      // A failed transport does not tell us whether UIKit/Android still shows
      // this dialog. Cancel its exact request and do not open a second modal.
      // Only an explicit handled:false response may use the web fallback.
      cancel();
    }).finally(() => { if (pending === item && !current(item)) cancel(); });
    return true;
  }
  window.tgNativeDialogs = {
    menu(title, items, quick, fallback) {
      if (quick || typeof title !== 'string' || !Array.isArray(items) || !items.length || items.length > 32 ||
          items.some(item => !Array.isArray(item) || typeof item[0] !== 'string' || !item[0] ||
            item[0].length > 256 || typeof item[1] !== 'function' || (item[2] && item[2] !== 'danger'))) return false;
      return start({kind: 'menu', title, actions: items.map(([label, , kind]) => ({label, destructive: kind === 'danger'}))},
        result => { if (Number.isInteger(result.index)) return items[result.index]?.[1](); }, fallback);
    },
    confirm(title, action, kind, fallback) {
      if (typeof title !== 'string' || typeof action !== 'function') return false;
      return start({kind: 'confirm', title, actions: [{label: t('Confirm'), destructive: kind === 'danger'}]},
        result => { if (result.index === 0) return action(); }, fallback);
    },
    prompt(title, options, action, fallback) {
      const type = options.type || 'text', maximum = options.maxlength || 4096;
      // Numeric/date validation and rich/custom fields remain the existing form.
      if (typeof title !== 'string' || !['text', 'password', 'email', 'tel', 'url'].includes(type) ||
          options.inputmode || !Number.isInteger(maximum) || maximum < 1 || maximum > 4096 ||
          typeof action !== 'function' || (options.value || '').length > maximum) return false;
      return start({kind: 'prompt', title, message: options.note || '', input_type: type,
        maxlength: maximum, value: options.value || '', placeholder: options.placeholder || '',
        actions: [{label: options.submit || t('Continuar')}]}, result => {
          if (result.index === 0 && typeof result.text === 'string' && result.text.length <= maximum) return action(result.text);
        }, fallback);
    },
    sync() { if (pending && !current(pending)) cancel(); },
    cancel,
  };
  document.addEventListener('visibilitychange', () => { if (document.hidden) cancel(); });
  window.addEventListener('pagehide', cancel);
})();
