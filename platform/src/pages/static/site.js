/* Commonworld v1 pages: Atlas behaviour (theme, announcement, drawer, sidebar toggle, search clear, tag shelf, consent + GA4 loader)
   copied from mockups/assets/mockup.js part 1, plus profile/catalog tabs and auto-submitting selects. No dependencies. */
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
  // ---- search placeholder: short "Search…" on narrow screens (full text stays in HTML for no-JS/agents)
  (function () {
    var q = document.getElementById('q');
    if (!q || !window.matchMedia) return;
    var full = q.getAttribute('placeholder') || '', mq = window.matchMedia('(max-width: 600px)');
    var apply = function () { q.setAttribute('placeholder', mq.matches ? 'Search\u2026' : full); };
    if (mq.addEventListener) mq.addEventListener('change', apply); else if (mq.addListener) mq.addListener(apply);
    apply();
  })();
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

  // ---- Consent Mode v2 + GA4, same behaviour as the Atlas (cw-components.js): gtag.js is loaded ONLY after "Accept".
  // The measurement id comes from the banner (data-ga, server env GA4_ID); no banner = no GA at all.
  // Defaults are set here instead of in an inline script, so the page CSP needs no extra hash or 'unsafe-inline'.
  var banner = document.querySelector('.cw-consent'), GA = banner && banner.getAttribute('data-ga'), loaded = false;
  function gtagStub() {
    if (window.gtag) return;
    window.dataLayer = window.dataLayer || [];
    window.gtag = function () { window.dataLayer.push(arguments); };
    window.gtag('consent', 'default', { ad_storage: 'denied', ad_user_data: 'denied', ad_personalization: 'denied',
      analytics_storage: 'denied', functionality_storage: 'denied', personalization_storage: 'denied', security_storage: 'granted' });
  }
  function loadGA() {
    if (loaded || !GA) return; loaded = true;
    gtagStub();
    window.gtag('consent', 'update', { analytics_storage: 'granted' });
    var s = document.createElement('script'); s.async = true;
    s.src = 'https://www.googletagmanager.com/gtag/js?id=' + encodeURIComponent(GA);
    document.head.appendChild(s);
    window.gtag('js', new Date()); window.gtag('config', GA);
  }
  function clearGACookies() {
    document.cookie.split(';').forEach(function (c) {
      var n = c.split('=')[0].trim();
      if (/^_ga/.test(n)) {
        var parts = location.hostname.split('.');
        for (var i = 0; i < parts.length; i++) document.cookie = n + '=; Max-Age=0; path=/; domain=' + parts.slice(i).join('.');
        document.cookie = n + '=; Max-Age=0; path=/';
      }
    });
  }
  function choose(v) {
    var prev = get('cw-consent'); set('cw-consent', v);
    if (banner) banner.hidden = true;
    if (v === 'granted') loadGA();
    else {
      if (window.gtag) window.gtag('consent', 'update', { analytics_storage: 'denied' });
      clearGACookies();
      if (prev === 'granted' && loaded) location.reload();
    }
  }
  if (GA && banner) {
    var c = get('cw-consent');
    if (c === 'granted') loadGA(); else if (c !== 'denied') banner.hidden = false;
    banner.querySelectorAll('[data-consent]').forEach(function (b) { b.addEventListener('click', function () { choose(b.getAttribute('data-consent')); }); });
    document.querySelectorAll('[data-cookie-settings]').forEach(function (b) {
      b.addEventListener('click', function () { banner.hidden = false; var f = banner.querySelector('button'); f && f.focus(); });
    });
  }
  // GA4 events only with analytics consent (none are sent by the product pages yet; Atlas key events stay Atlas-only).
  window.cwTrack = function (name, params) {
    if (get('cw-consent') === 'granted' && loaded && typeof window.gtag === 'function') window.gtag('event', name, params || {});
  };
})();

(function () {
  // tab groups: <div data-tabs="x"><button data-tab="a">…  + <div class="tabpanel" data-panel="x:a">
  document.querySelectorAll('[data-tabs]').forEach(function (group) {
    var name = group.getAttribute('data-tabs');
    group.querySelectorAll('[data-tab]').forEach(function (b) {
      b.addEventListener('click', function () {
        group.querySelectorAll('[data-tab]').forEach(function (o) { o.setAttribute('aria-pressed', o === b ? 'true' : 'false'); });
        document.querySelectorAll('[data-panel^="' + name + ':"]').forEach(function (p) {
          p.hidden = p.getAttribute('data-panel') !== name + ':' + b.getAttribute('data-tab');
          var cloud = p.querySelector('.cw-tagcloud');
          if (!p.hidden && cloud && cloud.cwRefresh) cloud.cwRefresh();
        });
      });
    });
  });
  // <select data-autosubmit> inside a GET form: submit on change (the form also has a button for no-JS)
  document.querySelectorAll('select[data-autosubmit]').forEach(function (s) {
    s.addEventListener('change', function () { if (s.form) s.form.submit(); });
  });
  document.querySelectorAll('.js-hide').forEach(function (el) { el.hidden = true; });
})();

(function () {
  // Hidden-post duck: click it 7 times (data-quack="7") and it answers "Quack." (aria-live status next to it).
  document.querySelectorAll('[data-quack]').forEach(function (b) {
    var need = parseInt(b.getAttribute('data-quack'), 10) || 7, n = 0;
    var msg = b.parentNode && b.parentNode.querySelector('.duck-quack');
    b.addEventListener('click', function () {
      n += 1;
      if (n >= need && msg) { msg.hidden = false; n = 0; }
    });
  });
})();
