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

  // ---- share buttons: copy link, native Web Share, GA4 'share' event only with analytics consent
  function shareEvent(method, url) {
    if (get('cw-consent') === 'granted' && typeof window.gtag === 'function' && window.CW_GA)
      window.gtag('event', 'share', { method: method, content_type: 'page', item_id: url });
  }
  function copyText(t) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(t);
    return new Promise(function (ok, bad) {
      var ta = document.createElement('textarea'); ta.value = t; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy') ? ok() : bad(); } catch (x) { bad(x); }
      document.body.removeChild(ta);
    });
  }
  document.querySelectorAll('.cw-share').forEach(function (bar) {
    var url = bar.getAttribute('data-share-url'), text = bar.getAttribute('data-share-text'), status = bar.querySelector('.cw-share-status');
    var nat = bar.querySelector('[data-share="native"]');
    var touch = window.matchMedia && window.matchMedia('(pointer: coarse)').matches;
    if (nat && navigator.share && touch) nat.hidden = false;
    bar.addEventListener('click', function (ev) {
      var b = ev.target.closest('[data-share]');
      if (!b || !bar.contains(b)) return;
      var m = b.getAttribute('data-share');
      if (m === 'copy') {
        var txt = b.querySelector('.cw-share-txt');
        copyText(url).then(function () {
          b.classList.add('copied'); if (txt) txt.textContent = 'Copied'; if (status) status.textContent = 'Link copied';
          setTimeout(function () { b.classList.remove('copied'); if (txt) txt.textContent = 'Copy link'; if (status) status.textContent = ''; }, 2000);
          shareEvent('copy', url);
        }, function () { if (status) status.textContent = 'Could not copy. The link is ' + url; });
      } else if (m === 'native') {
        navigator.share({ title: document.title, text: text, url: url }).then(function () { shareEvent('native', url); }, function () {});
      } else {
        shareEvent(m, url);  // plain link: the browser follows the share-intent URL
      }
    });
  });

  // ---- Consent Mode v2 + GA4: gtag.js is only loaded after "Accept"
  var GA = window.CW_GA, banner = document.querySelector('.cw-consent'), loaded = false;
  function loadGA() {
    if (loaded || !GA) return; loaded = true;
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
    else if (window.gtag) {
      window.gtag('consent', 'update', { analytics_storage: 'denied' }); clearGACookies();
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
})();
