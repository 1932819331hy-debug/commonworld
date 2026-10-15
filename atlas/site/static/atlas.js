/* Atlas index: instant search + filters (category, status, type, features, tags — all combined with AND),
   sorting, live counts, URL state, and native sponsored cards re-inserted after every 12 visible cards. */
(function () {
  var root = document.getElementById('catalog');
  var grid = document.getElementById('grid');
  if (!root || !grid) return;
  var EVERY = 12;
  var CATS = JSON.parse(document.getElementById('cat-labels').textContent);
  var TYPES = JSON.parse(document.getElementById('type-labels').textContent);
  var q = document.getElementById('q'), form = q && q.closest('form');
  var cards = Array.prototype.slice.call(grid.querySelectorAll('.cw-card[data-slug]'));
  var total = cards.length;
  var adTpl = grid.querySelector('[data-ad-card]');
  if (adTpl) adTpl = adTpl.cloneNode(true);
  var empty = document.getElementById('f-empty');
  var shelfEl = document.getElementById('tagcloud');
  var shelfMore = shelfEl && shelfEl.querySelector('.cw-tags-more');
  var tagBtns = shelfEl ? Array.prototype.slice.call(shelfEl.querySelectorAll('[data-tag]')) : [];
  var state = { q: '', cat: '', status: new Set(), type: new Set(), feat: new Set(), tags: new Set(), sort: 'name' };

  cards.forEach(function (c) {
    c._tags = (c.getAttribute('data-tags') || '').split(' ').filter(Boolean);
    c._hay = (c.textContent + ' ' + (CATS[c.dataset.c] || '') + ' ' + c.dataset.c + ' ' + (TYPES[c.dataset.t] || '') + ' ' + c._tags.join(' ')).toLowerCase();
    c._name = (c.querySelector('h3') || c).textContent.trim().toLowerCase();
  });

  // claim statements are searched too: loaded once, on first interaction (keeps the page light)
  var extraLoaded = false;
  function loadExtra() {
    if (extraLoaded || !window.fetch) return; extraLoaded = true;
    fetch(root.getAttribute('data-search-index')).then(function (r) { return r.json(); }).then(function (idx) {
      cards.forEach(function (c) { var x = idx[c.dataset.slug]; if (x) c._hay += ' ' + x.toLowerCase(); });
      apply(false);
    }).catch(function () {});
  }

  function match(c, skip) {
    var words = state.q.toLowerCase().split(/\s+/).filter(Boolean);
    if (skip !== 'cat' && state.cat && c.dataset.c !== state.cat) return false;
    if (skip !== 'status' && state.status.size && !state.status.has(c.dataset.s)) return false;
    if (skip !== 'type' && state.type.size && !state.type.has(c.dataset.t)) return false;
    if (skip !== 'feat') { var ok = true; state.feat.forEach(function (f) { if (c.dataset[f] !== '1') ok = false; }); if (!ok) return false; }
    if (skip !== 'tags') { var ok2 = true; state.tags.forEach(function (t) { if (c._tags.indexOf(t) === -1) ok2 = false; }); if (!ok2) return false; }
    for (var i = 0; i < words.length; i++) if (c._hay.indexOf(words[i]) === -1) return false;
    return true;
  }
  function countBy(skip, fn) { var n = 0; cards.forEach(function (c) { if (match(c, skip) && fn(c)) n++; }); return n; }

  function sortCards() {
    var by = state.sort, l = cards.slice();
    var name = function (a, b) { return a._name < b._name ? -1 : a._name > b._name ? 1 : 0; };
    if (by === 'claims') l.sort(function (a, b) { return (+b.dataset.claims) - (+a.dataset.claims) || name(a, b); });
    else if (by === 'recent') l.sort(function (a, b) { return (+b.dataset.ver) - (+a.dataset.ver) || name(a, b); });
    else l.sort(name);
    return l;
  }

  function placeAds(visible) {
    grid.querySelectorAll('[data-ad-card]').forEach(function (a) { a.remove(); });
    if (!adTpl) return;
    for (var i = EVERY - 1; i < visible.length; i += EVERY) visible[i].after(adTpl.cloneNode(true));
  }

  function pressed(el, on) { el.setAttribute('aria-pressed', on ? 'true' : 'false'); el.classList.toggle('active', !!on); }

  function apply(push) {
    var ordered = sortCards(), visible = [];
    ordered.forEach(function (c) { grid.appendChild(c); var ok = match(c); c.hidden = !ok; if (ok) visible.push(c); });
    if (empty) grid.appendChild(empty);
    placeAds(visible);
    empty.hidden = visible.length !== 0;
    document.getElementById('list-title').textContent = state.cat ? CATS[state.cat] : 'All platforms';
    document.getElementById('list-count').textContent = visible.length + ' of ' + total;

    // chip counts (each group counted with every other filter applied)
    document.querySelectorAll('[data-f-status]').forEach(function (b) {
      var k = b.getAttribute('data-f-status'); pressed(b, state.status.has(k));
      b.querySelector('span').textContent = countBy('status', function (c) { return c.dataset.s === k; });
    });
    document.querySelectorAll('[data-f-type]').forEach(function (b) {
      var k = b.getAttribute('data-f-type'); pressed(b, state.type.has(k));
      b.querySelector('span').textContent = countBy('type', function (c) { return c.dataset.t === k; });
    });
    document.querySelectorAll('[data-f-feat]').forEach(function (b) {
      var k = b.getAttribute('data-f-feat'); pressed(b, state.feat.has(k));
      b.querySelector('span').textContent = countBy('feat', function (c) { return c.dataset[k] === '1'; });
    });
    document.querySelectorAll('[data-filter]').forEach(function (b) {
      var f = b.getAttribute('data-filter').split(':');
      pressed(b, f[0] === 'status' ? state.status.has(f[1]) : f[0] === 'feat' ? state.feat.has(f[1]) : false);
    });
    document.querySelectorAll('#catalog-top [data-cat], .cw-legend [data-cat]').forEach(function (b) { pressed(b, (b.getAttribute('data-cat') || '') === state.cat); });
    document.querySelectorAll('.cw-side a[data-cat]').forEach(function (a) {
      var on = (a.getAttribute('data-cat') || '') === state.cat; a.classList.toggle('active', on);
      if (on) a.setAttribute('aria-current', 'true'); else a.removeAttribute('aria-current');
    });

    // tag shelf: counts within the current filters, selected first, then by count; empty tags hidden
    if (shelfEl) {
      var counts = {};
      cards.forEach(function (c) { if (match(c, 'tags')) c._tags.forEach(function (t) { counts[t] = (counts[t] || 0) + 1; }); });
      tagBtns.sort(function (a, b) {
        var ta = a.dataset.tag, tb = b.dataset.tag;
        return (state.tags.has(tb) - state.tags.has(ta)) || ((counts[tb] || 0) - (counts[ta] || 0)) || (ta < tb ? -1 : 1);
      });
      tagBtns.forEach(function (b) {
        var t = b.dataset.tag, n = counts[t] || 0;
        b.querySelector('small').textContent = n; pressed(b, state.tags.has(t));
        b.hidden = !n && !state.tags.has(t);
        shelfEl.insertBefore(b, shelfMore);
      });
      shelfEl.cwRefresh && shelfEl.cwRefresh();
    }
    grid.querySelectorAll('.card-tags [data-tag]').forEach(function (a) { a.classList.toggle('active', state.tags.has(a.dataset.tag)); });
    renderActive(visible.length);

    if (push) {
      var p = new URLSearchParams();
      if (state.q) p.set('q', state.q);
      if (state.cat) p.set('category', state.cat);
      if (state.status.size) p.set('status', Array.from(state.status).join(','));
      if (state.type.size) p.set('type', Array.from(state.type).join(','));
      if (state.feat.size) p.set('feature', Array.from(state.feat).join(','));
      if (state.tags.size) p.set('tag', Array.from(state.tags).join(','));
      if (state.sort !== 'name') p.set('sort', state.sort);
      var s = p.toString(); history.replaceState(null, '', location.pathname + (s ? '?' + s : '') + location.hash);
    }
  }

  var esc = function (s) { return String(s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };
  var FEAT = { money: 'has money flow', num: 'has numbers' };
  function renderActive(n) {
    var parts = [];
    if (state.cat) parts.push(['cat', CATS[state.cat]]);
    state.status.forEach(function (s) { parts.push(['st:' + s, s]); });
    state.type.forEach(function (t) { parts.push(['ty:' + t, TYPES[t] || t]); });
    state.feat.forEach(function (f) { parts.push(['ft:' + f, FEAT[f]]); });
    state.tags.forEach(function (t) { parts.push(['tag:' + t, '#' + t]); });
    if (state.q) parts.push(['q', '«' + state.q + '»']);
    var el = document.getElementById('active');
    el.innerHTML = parts.length
      ? '<span>Filters (all at once):</span>' + parts.map(function (p) { return '<button class="link-pill active" type="button" data-x="' + esc(p[0]) + '" aria-label="Remove filter ' + esc(p[1]) + '">' + esc(p[1]) + ' ×</button>'; }).join('') + '<span>→ found <b>' + n + '</b></span>'
      : '<span>Click tags, statuses or tabs to narrow the list. Tags combine with AND.</span>';
  }

  function toggle(set, k) { set.has(k) ? set.delete(k) : set.add(k); }
  function setCat(k) { state.cat = state.cat === k && k ? '' : k; }
  function resetAll() {
    state.q = ''; state.cat = ''; state.status.clear(); state.type.clear(); state.feat.clear(); state.tags.clear();
    if (q) { q.value = ''; q.dispatchEvent(new Event('input')); }
  }
  function goCatalog() { root.scrollIntoView({ behavior: 'smooth', block: 'start' }); }

  document.addEventListener('click', function (ev) {
    var t = ev.target.closest('[data-f-status],[data-f-type],[data-f-feat],[data-filter],[data-cat],[data-tag],[data-x],#f-reset');
    if (!t || t.classList.contains('cw-tags-more')) return;
    if (t.tagName === 'A' && (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.button === 1)) return;
    if (t.closest('.cw-side') && !t.hasAttribute('data-cat')) return;
    ev.preventDefault();
    if (t.id === 'f-reset') resetAll();
    else if (t.hasAttribute('data-f-status')) toggle(state.status, t.getAttribute('data-f-status'));
    else if (t.hasAttribute('data-f-type')) toggle(state.type, t.getAttribute('data-f-type'));
    else if (t.hasAttribute('data-f-feat')) toggle(state.feat, t.getAttribute('data-f-feat'));
    else if (t.hasAttribute('data-filter')) {
      var f = t.getAttribute('data-filter').split(':');
      if (f[0] === 'reset') resetAll(); else toggle(f[0] === 'status' ? state.status : state.feat, f[1]);
      goCatalog();
    } else if (t.hasAttribute('data-cat')) { setCat(t.getAttribute('data-cat')); if (!t.closest('#catalog-top')) goCatalog(); }
    else if (t.hasAttribute('data-tag')) toggle(state.tags, t.getAttribute('data-tag'));
    else if (t.hasAttribute('data-x')) {
      var x = t.getAttribute('data-x');
      if (x === 'cat') state.cat = '';
      else if (x === 'q') { state.q = ''; q.value = ''; q.dispatchEvent(new Event('input')); }
      else { var kv = x.split(':'), v = x.slice(kv[0].length + 1); ({ st: state.status, ty: state.type, ft: state.feat, tag: state.tags })[kv[0]].delete(v); }
    }
    loadExtra(); apply(true);
  });

  var timer;
  if (q) {
    q.addEventListener('focus', loadExtra);
    q.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(function () { state.q = q.value.trim(); apply(true); }, 80); });
  }
  if (form) form.addEventListener('submit', function (ev) { ev.preventDefault(); state.q = q.value.trim(); apply(true); goCatalog(); });
  var sortEl = document.getElementById('f-sort');
  sortEl.addEventListener('change', function () { state.sort = sortEl.value; apply(true); });

  // restore from URL (?q=&category=&status=&type=&feature=&tag=&sort=)
  var P = new URLSearchParams(location.search), list = function (k) { return (P.get(k) || '').split(',').filter(Boolean); };
  state.q = (P.get('q') || '').trim(); if (q) { q.value = state.q; q.dispatchEvent(new Event('input')); clearTimeout(timer); }
  if (CATS[P.get('category')]) state.cat = P.get('category');
  list('status').forEach(function (s) { if (s === 'live' || s === 'closed') state.status.add(s); });
  list('type').forEach(function (s) { if (TYPES[s]) state.type.add(s); });
  list('feature').forEach(function (s) { if (FEAT[s]) state.feat.add(s); });
  list('tag').forEach(function (s) { state.tags.add(s.toLowerCase()); });
  if (['name', 'claims', 'recent'].indexOf(P.get('sort')) !== -1) { state.sort = P.get('sort'); sortEl.value = state.sort; }
  if (state.q) loadExtra();
  apply(false);
})();
