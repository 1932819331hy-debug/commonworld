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
  var baseOrder = cards.slice();  // sorts always start from the page order, as before
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

  // Each apply() makes ONE pass over the cards: every card gets a bitmask of the filter groups it fails, so the list,
  // every chip count and the tag shelf all come from that pass. The DOM is only touched where something changed
  // (cards are reordered only when the sort changes; hidden / pressed / counts are written only when they differ).
  var G = { cat: 1, status: 2, type: 4, feat: 8, tags: 16, q: 32 };
  function failMask(c, words) {
    var m = 0;
    if (state.cat && c.dataset.c !== state.cat) m |= G.cat;
    if (state.status.size && !state.status.has(c.dataset.s)) m |= G.status;
    if (state.type.size && !state.type.has(c.dataset.t)) m |= G.type;
    if (state.feat.size) state.feat.forEach(function (f) { if (c.dataset[f] !== '1') m |= G.feat; });
    if (state.tags.size) state.tags.forEach(function (t) { if (c._tags.indexOf(t) === -1) m |= G.tags; });
    for (var i = 0; i < words.length; i++) if (c._hay.indexOf(words[i]) === -1) { m |= G.q; break; }
    return m;
  }

  function sortCards() {
    var by = state.sort, l = baseOrder.slice();
    var name = function (a, b) { return a._name < b._name ? -1 : a._name > b._name ? 1 : 0; };
    if (by === 'claims') l.sort(function (a, b) { return (+b.dataset.claims) - (+a.dataset.claims) || name(a, b); });
    else if (by === 'recent') l.sort(function (a, b) { return (+b.dataset.ver) - (+a.dataset.ver) || name(a, b); });
    else l.sort(name);
    return l;
  }

  // sponsored cards: a small pool of nodes moved into place (no re-cloning on every filter)
  var adPool = Array.prototype.slice.call(grid.querySelectorAll('[data-ad-card]'));
  function placeAds(visible) {
    var need = adTpl ? Math.floor(visible.length / EVERY) : 0;
    while (adPool.length < need) adPool.push(adTpl.cloneNode(true));
    for (var i = 0; i < adPool.length; i++) {
      var ad = adPool[i];
      if (i < need) { var anchor = visible[(i + 1) * EVERY - 1]; if (anchor.nextSibling !== ad) anchor.after(ad); }
      else if (ad.parentNode) ad.remove();
    }
  }

  function pressed(el, on) {
    var v = on ? 'true' : 'false';
    if (el.getAttribute('aria-pressed') !== v) el.setAttribute('aria-pressed', v);
    if (el.classList.contains('active') !== !!on) el.classList.toggle('active', !!on);
  }
  function setText(el, t) { t = String(t); if (el.textContent !== t) el.textContent = t; }
  function all(sel) { return Array.prototype.slice.call(document.querySelectorAll(sel)); }
  var statusBtns = all('[data-f-status]'), typeBtns = all('[data-f-type]'), featBtns = all('[data-f-feat]'), filterBtns = all('[data-filter]');
  var catBtns = all('#catalog-top [data-cat], .cw-legend [data-cat]'), sideCats = all('.cw-side a[data-cat]');
  var cardTagLinks = Array.prototype.slice.call(grid.querySelectorAll('.card-tags [data-tag]'));
  var listTitle = document.getElementById('list-title'), listCount = document.getElementById('list-count');
  var sortedFor = null, tagsKey = null, activeHTML = null;

  function apply(push) {
    var words = state.q.toLowerCase().split(/\s+/).filter(Boolean);
    if (sortedFor !== state.sort) {  // reorder only when the sort changes
      sortedFor = state.sort;
      var frag = document.createDocumentFragment();
      sortCards().forEach(function (c) { frag.appendChild(c); });
      if (empty) frag.appendChild(empty);
      grid.appendChild(frag);
      cards = Array.prototype.slice.call(grid.querySelectorAll('.cw-card[data-slug]'));
    }
    var visible = [], cS = {}, cT = {}, cF = { money: 0, num: 0 }, tagCounts = {};
    var notS = ~G.status, notT = ~G.type, notF = ~G.feat, notTg = ~G.tags;
    for (var i = 0; i < cards.length; i++) {
      var c = cards[i], m = failMask(c, words), ok = m === 0;
      if (c.hidden === ok) c.hidden = !ok;
      if (ok) visible.push(c);
      if ((m & notS) === 0) cS[c.dataset.s] = (cS[c.dataset.s] || 0) + 1;
      if ((m & notT) === 0) cT[c.dataset.t] = (cT[c.dataset.t] || 0) + 1;
      if ((m & notF) === 0) { if (c.dataset.money === '1') cF.money++; if (c.dataset.num === '1') cF.num++; }
      if ((m & notTg) === 0) for (var j = 0; j < c._tags.length; j++) tagCounts[c._tags[j]] = (tagCounts[c._tags[j]] || 0) + 1;
    }
    placeAds(visible);
    if (empty && empty.hidden !== (visible.length !== 0)) empty.hidden = visible.length !== 0;
    setText(listTitle, state.cat ? CATS[state.cat] : 'All platforms');
    setText(listCount, visible.length + ' of ' + total);

    // chip counts (each group counted with every other filter applied)
    statusBtns.forEach(function (b) { var k = b.getAttribute('data-f-status'); pressed(b, state.status.has(k)); setText(b.querySelector('span'), cS[k] || 0); });
    typeBtns.forEach(function (b) { var k = b.getAttribute('data-f-type'); pressed(b, state.type.has(k)); setText(b.querySelector('span'), cT[k] || 0); });
    featBtns.forEach(function (b) { var k = b.getAttribute('data-f-feat'); pressed(b, state.feat.has(k)); setText(b.querySelector('span'), cF[k] || 0); });
    filterBtns.forEach(function (b) {
      var f = b.getAttribute('data-filter').split(':');
      pressed(b, f[0] === 'status' ? state.status.has(f[1]) : f[0] === 'feat' ? state.feat.has(f[1]) : false);
    });
    catBtns.forEach(function (b) { pressed(b, (b.getAttribute('data-cat') || '') === state.cat); });
    sideCats.forEach(function (a) {
      var on = (a.getAttribute('data-cat') || '') === state.cat;
      if (a.classList.contains('active') !== on) a.classList.toggle('active', on);
      if (on) { if (a.getAttribute('aria-current') !== 'true') a.setAttribute('aria-current', 'true'); } else if (a.hasAttribute('aria-current')) a.removeAttribute('aria-current');
    });

    // tag shelf: counts within the current filters, selected first, then by count; empty tags hidden
    if (shelfEl) {
      var prev = tagBtns.slice();
      tagBtns.sort(function (a, b) {
        var ta = a.dataset.tag, tb = b.dataset.tag;
        return (state.tags.has(tb) - state.tags.has(ta)) || ((tagCounts[tb] || 0) - (tagCounts[ta] || 0)) || (ta < tb ? -1 : 1);
      });
      var moved = tagBtns.some(function (b, i) { return b !== prev[i]; });
      var frag2 = moved ? document.createDocumentFragment() : null;
      tagBtns.forEach(function (b) {
        var t = b.dataset.tag, n = tagCounts[t] || 0, hide = !n && !state.tags.has(t);
        setText(b.querySelector('small'), n); pressed(b, state.tags.has(t));
        if (b.hidden !== hide) b.hidden = hide;
        if (frag2) frag2.appendChild(b);
      });
      if (frag2) shelfEl.insertBefore(frag2, shelfMore);
      shelfEl.cwRefresh && shelfEl.cwRefresh();
    }
    var tk = Array.from(state.tags).join(' ');
    if (tk !== tagsKey) { tagsKey = tk; cardTagLinks.forEach(function (a) { var on = state.tags.has(a.dataset.tag); if (a.classList.contains('active') !== on) a.classList.toggle('active', on); }); }
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
    var h = parts.length
      ? '<span>Filters (all at once):</span>' + parts.map(function (p) { return '<button class="link-pill active" type="button" data-x="' + esc(p[0]) + '" aria-label="Remove filter ' + esc(p[1]) + '">' + esc(p[1]) + ' ×</button>'; }).join('') + '<span>→ found <b>' + n + '</b></span>'
      : '<span>Click tags, statuses or tabs to narrow the list. Tags combine with AND.</span>';
    if (h !== activeHTML) { activeHTML = h; el.innerHTML = h; }
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

/* Card pages: "Add this badge to your site" copy buttons (shown only when JS runs; the code stays selectable without it). */
(function () {
  var btns = document.querySelectorAll('.badge-copy[data-copy-for]');
  if (!btns.length) return;
  var status = document.querySelector('.badge-status');
  function copyText(t) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(t);
    return new Promise(function (ok, bad) {
      var ta = document.createElement('textarea'); ta.value = t; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy') ? ok() : bad(); } catch (x) { bad(x); }
      document.body.removeChild(ta);
    });
  }
  Array.prototype.forEach.call(btns, function (b) {
    var src = document.getElementById(b.getAttribute('data-copy-for'));
    if (!src) return;
    b.hidden = false;
    b.addEventListener('click', function () {
      copyText(src.textContent).then(function () {
        b.classList.add('copied'); b.textContent = 'Copied'; if (status) status.textContent = 'Badge code copied';
        setTimeout(function () { b.classList.remove('copied'); b.textContent = 'Copy'; if (status) status.textContent = ''; }, 2000);
      }, function () { if (status) status.textContent = 'Could not copy. Select the code and copy it by hand.'; });
    });
  });
})();
