/* Mockup JS. Part 1: copied from Atlas components/cw-components.js (theme, announcement, drawer, sidebar toggle, search clear, tag shelf) — share/consent/GA parts left out. */
/* Commonworld design-system behaviour: theme toggle, announcement dismissal, consent + GA4 loader,
   sidebar drawer, search clear button, tag shelf expander. No dependencies. Exposes window.CW helpers. */
(function () {
  var d = document.documentElement, store;
  try { store = window.localStorage; } catch (x) { store = null; }
  function get(k) { try { return store && store.getItem(k); } catch (x) { return null; } }
  function set(k, v) { try { store && store.setItem(k, v); } catch (x) {} }

  // ---- theme (initial theme is set by the inline boot script, before paint)
  function syncThemeLabels() {
    var dark = d.getAttribute('data-theme') === 'dark';
    document.querySelectorAll('.cw-theme').forEach(function (b) { b.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme'); });
  }
  document.querySelectorAll('.cw-theme').forEach(function (b) {
    b.addEventListener('click', function () {
      var next = d.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      d.setAttribute('data-theme', next); set('cw-theme', next); syncThemeLabels();
    });
  });
  syncThemeLabels();

  // ---- announcement bar: dismissal remembered per message id
  document.querySelectorAll('.cw-announce').forEach(function (bar) {
    var btn = bar.querySelector('.cw-announce-x');
    btn && btn.addEventListener('click', function () { set('cw-ann-dismissed', bar.getAttribute('data-ann-id')); d.classList.add('cw-ann-off'); });
  });

  // ---- sidebar drawer (tablet / mobile)
  var side = document.getElementById('cw-side'), scrim = document.querySelector('.cw-scrim'), menu = document.querySelector('.cw-menu');
  function drawer(open) {
    d.classList.toggle('cw-drawer-open', open);
    if (scrim) scrim.hidden = !open;
    if (menu) { menu.setAttribute('aria-expanded', open ? 'true' : 'false'); menu.setAttribute('aria-label', open ? 'Close menu' : 'Open menu'); }
    if (open && side) { var f = side.querySelector('a'); f && f.focus(); } else if (!open && menu && side && side.contains(document.activeElement)) menu.focus();
  }
  if (menu) menu.addEventListener('click', function () { drawer(!d.classList.contains('cw-drawer-open')); });
  if (scrim) scrim.addEventListener('click', function () { drawer(false); });
  document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape' && d.classList.contains('cw-drawer-open')) drawer(false); });
  if (side) side.addEventListener('click', function (ev) { if (ev.target.closest('a') && d.classList.contains('cw-drawer-open')) drawer(false); });
  window.addEventListener('resize', function () { if (window.innerWidth > 900 && d.classList.contains('cw-drawer-open')) drawer(false); });

  // ---- sidebar hide / show (desktop > 900px; the drawer above keeps the tablet / mobile behaviour).
  // The stored state is applied before paint by the inline boot script (class cw-side-off on <html>).
  function syncSide() {
    var off = d.classList.contains('cw-side-off');
    document.querySelectorAll('.cw-sidetoggle').forEach(function (b) {
      var l = off ? 'Show sidebar' : 'Hide sidebar';
      b.setAttribute('aria-expanded', off ? 'false' : 'true'); b.setAttribute('aria-label', l); b.setAttribute('title', l);
    });
  }
  document.querySelectorAll('.cw-sidetoggle').forEach(function (b) {
    b.addEventListener('click', function () {
      var off = !d.classList.contains('cw-side-off');
      d.classList.toggle('cw-side-off', off);
      if (off) set('cw-side', 'off'); else { try { store && store.removeItem('cw-side'); } catch (x) {} }
      syncSide();
    });
  });
  syncSide();

  // ---- search: clear button + "/" shortcut
  document.querySelectorAll('.cw-search-wrap').forEach(function (f) {
    var q = f.querySelector('.cw-search'), x = f.querySelector('.cw-search-clear');
    if (!q || !x) return;
    var sync = function () { x.hidden = !q.value; };
    q.addEventListener('input', sync); sync();
    x.addEventListener('click', function () { q.value = ''; sync(); q.dispatchEvent(new Event('input', { bubbles: true })); q.focus(); });
  });
  document.addEventListener('keydown', function (ev) {
    var q = document.getElementById('q'), t = ev.target;
    if (ev.key === '/' && q && t !== q && !/^(INPUT|SELECT|TEXTAREA)$/.test(t.tagName)) { ev.preventDefault(); q.focus(); }
  });

  // ---- tag shelf ("козырек"): clipped row + "all tags (N) ↓" expander
  function shelf(el) {
    var btn = el.querySelector('.cw-tags-more');
    if (!btn) return;
    var label = function () {
      var n = el.querySelectorAll('[data-tag]:not([hidden])').length, open = el.classList.contains('open');
      btn.textContent = open ? 'collapse tags' : 'all tags (' + n + ') ↓';
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    };
    // Collapsed shelf: a chip that is cut off by the clip edge or sits under the expander stays visible as a hint
    // but is made inert (not focusable, not tappable, not announced), so no button has a 3px hit area (WCAG 2.5.8).
    var clip = function () {
      var open = el.classList.contains('open') || el.classList.contains('fits');
      var r = el.getBoundingClientRect(), lim = r.top + el.clientTop + el.clientHeight + 0.5, br = btn.getBoundingClientRect();
      el.querySelectorAll('[data-tag]').forEach(function (t) {
        var c = t.getBoundingClientRect(), cut = false;
        if (!open && !t.hidden) cut = c.bottom > lim || (c.right > br.left && c.left < br.right && c.bottom > br.top && c.top < br.bottom);
        if (cut) { t.setAttribute('inert', ''); t.classList.add('cw-clip'); } else if (t.classList.contains('cw-clip')) { t.removeAttribute('inert'); t.classList.remove('cw-clip'); }
      });
    };
    var fit = function () {
      if (el.classList.contains('open')) { el.classList.remove('fits'); clip(); return; }
      el.classList.remove('fits');
      el.classList.toggle('fits', el.scrollHeight <= el.clientHeight + 2);
      clip();
    };
    btn.addEventListener('click', function () { el.classList.toggle('open'); label(); fit(); });
    el.cwRefresh = function () { label(); fit(); };
    window.addEventListener('resize', fit);
    window.addEventListener('load', fit);  // chips can reflow once fonts / styles settle
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(fit);
    el.cwRefresh();
  }
  document.querySelectorAll('.cw-tagcloud').forEach(shelf);

})();

/* Part 2: mockup-only behaviour (vanilla, no framework). */
(function () {
  // tab groups: <div data-tabs="x"><button data-tab="a">…  + <div class="tabpanel" data-panel="x:a">
  document.querySelectorAll('[data-tabs]').forEach(function (group) {
    var name = group.getAttribute('data-tabs');
    group.querySelectorAll('[data-tab]').forEach(function (b) {
      b.addEventListener('click', function () {
        group.querySelectorAll('[data-tab]').forEach(function (o) { o.setAttribute('aria-pressed', o === b ? 'true' : 'false'); });
        document.querySelectorAll('[data-panel^="' + name + ':"]').forEach(function (p) { p.hidden = p.getAttribute('data-panel') !== name + ':' + b.getAttribute('data-tab'); });
      });
    });
  });
  // single-choice pill groups (cosmetic in the mockup)
  document.querySelectorAll('[data-choice]').forEach(function (group) {
    group.querySelectorAll('button').forEach(function (b) {
      b.addEventListener('click', function () { group.querySelectorAll('button').forEach(function (o) { o.setAttribute('aria-pressed', o === b ? 'true' : 'false'); }); });
    });
  });
  // kind filter: <… data-kind-filter> buttons with data-kind=all|human|agent; rows/cards carry data-kind
  document.querySelectorAll('[data-kind-filter]').forEach(function (group) {
    var scope = document.querySelector(group.getAttribute('data-kind-filter'));
    group.querySelectorAll('button[data-kind]').forEach(function (b) {
      b.addEventListener('click', function () {
        var k = b.getAttribute('data-kind');
        if (scope) scope.querySelectorAll('[data-kind]').forEach(function (el) { el.hidden = k !== 'all' && el.getAttribute('data-kind') !== k; });
      });
    });
  });
  // leaderboard sort: buttons data-sort=<column>; rows carry data-<column>
  document.querySelectorAll('[data-sort-table]').forEach(function (group) {
    var table = document.querySelector(group.getAttribute('data-sort-table'));
    if (!table) return;
    var body = table.tBodies[0];
    group.querySelectorAll('button[data-sort]').forEach(function (b) {
      b.addEventListener('click', function () {
        var key = b.getAttribute('data-sort');
        var rows = Array.prototype.slice.call(body.rows);
        rows.sort(function (x, y) { return Number(y.dataset[key]) - Number(x.dataset[key]) || Number(x.dataset.number) - Number(y.dataset.number); });
        rows.forEach(function (r, i) { body.appendChild(r); r.querySelector('.rk').textContent = i + 1; });
        table.querySelectorAll('th[data-col]').forEach(function (th) { th.classList.toggle('sorted', th.getAttribute('data-col') === key); });
      });
    });
  });
})();
