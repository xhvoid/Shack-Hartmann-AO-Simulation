// Hash routes keep earlier study links usable while showing one view at a time.
export function initNavigation() {
  const views = [...document.querySelectorAll('[data-view]')];
  let current;
  function route() {
    let id;
    try { id = decodeURIComponent(location.hash.slice(1)); } catch { id = ''; }
    let target = document.getElementById(id || 'overview');
    const view = target?.closest('[data-view]') || document.getElementById(id.startsWith('result-') ? 'appendix' : 'overview');
    const changed = current !== view.id;
    for (const item of views) item.hidden = item !== view;
    current = view.id;
    for (const link of document.querySelectorAll('[data-nav-link]')) {
      if (link.dataset.navLink === view.dataset.nav) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    }
    // Open the containing image view or disclosure before scrolling a deep link.
    if (target) {
      const topic = target.closest('.topic-panel');
      if (topic) {
        for (const panel of document.querySelectorAll('.topic-panel')) panel.hidden = panel !== topic;
        for (const button of document.querySelectorAll('[data-topic]')) button.setAttribute('aria-pressed', String('topic-' + button.dataset.topic === topic.id));
      }
      const pane = target.closest('[data-pane-content]');
      if (pane) selectPane(pane.dataset.paneContent);
      for (let node = target; node && node !== view; node = node.parentElement) {
        if (node.tagName === 'DETAILS') node.open = true;
      }
    }
    document.title = `${view.querySelector('h1')?.textContent || 'AO Simulation Explorer'} · AO Explorer`;
    if (changed) document.dispatchEvent(new CustomEvent('ao:viewchange', {detail: {view: current}}));
    requestAnimationFrame(() => {
      (target || view).scrollIntoView({block: 'start'});
      window.dispatchEvent(new Event('resize'));
    });
  }
  function selectPane(name) {
    const button = document.querySelector(`[data-pane="${name}"]`);
    if (!button) return;
    const group = button.parentElement;
    for (const item of group.querySelectorAll('[data-pane]')) {
      const active = item === button;
      item.setAttribute('aria-pressed', String(active));
      document.querySelector(`[data-pane-content="${item.dataset.pane}"]`).hidden = !active;
    }
    requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
  }
  for (const button of document.querySelectorAll('[data-pane]')) button.addEventListener('click', () => selectPane(button.dataset.pane));
  window.addEventListener('hashchange', route);
  route();
}
