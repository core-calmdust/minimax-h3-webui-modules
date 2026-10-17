
() => {
  /* ⚠️ 原本は隠し箱に残し、見出しへは **複製**を置く。移してしまうと、
     Markdown（LoRA の件数・SEGMENTS の見出しなど）が値の更新で描き直された
     ときに複製ごと消えて、二度と戻らない（実機で確認） */
  function place() {
    document.querySelectorAll('.h3-help-wrap[data-anchor]').forEach(function (w) {
      var src = w.querySelector('.h3-help');
      if (!src) return;
      var t = document.querySelector(w.getAttribute('data-anchor'));
      if (!t) return;                          /* 見出しがまだ無い */
      var id = w.getAttribute('data-help');
      var cur = t.querySelector('.h3-help[data-help="' + id + '"]');
      if (cur && cur.innerHTML === src.innerHTML) return;   /* 最新が置いてある */
      if (cur) cur.remove();                   /* 言語切替で文言が変わった */
      var c = src.cloneNode(true);
      c.setAttribute('data-help', id);
      t.appendChild(c);
    });
  }
  /* 🆕 ver1.7 #361 高速化の「高速化」とプルダウンの文字を、ドラフトモードの文字と同じ見た目にする（テーマ切替にも追従） */
  function syncAccel() {
    var src = document.querySelector('#t2i-fast label .label-text') || document.querySelector('#t2i-fast label span');
    if (!src) return;
    var c = getComputedStyle(src);
    ['#accel-lbl .accel-lbl-t', '#accel-dd input'].forEach(function (sel) {
      var d = document.querySelector(sel);
      if (!d) return;
      ['fontSize', 'fontWeight', 'color', 'letterSpacing', 'fontFamily'].forEach(function (k) {
        if (d.style[k] !== c[k]) d.style.setProperty(k.replace(/[A-Z]/g, function (m) { return '-' + m.toLowerCase(); }), c[k], 'important');
      });
    });
    /* #363 「高速化」の ？ をドラフトモードの ？ と同じ見た目に（HTML の箱は prose の書式が乗るので、計算後の値を写す） */
    var hs = document.querySelector('#t2i-fast .h3-help'), hd = document.querySelector('#accel-lbl .h3-help');
    if (hs && hd) {
      var hc = getComputedStyle(hs);
      ['color', 'fontSize', 'fontWeight', 'fontFamily', 'letterSpacing', 'lineHeight', 'width', 'height',
       'borderTopColor', 'borderTopWidth', 'backgroundColor', 'marginLeft'].forEach(function (k) {
        var css = k.replace(/[A-Z]/g, function (m) { return '-' + m.toLowerCase(); });
        if (k === 'borderTopColor') css = 'border-color';
        if (k === 'borderTopWidth') css = 'border-width';
        if (hd.style.getPropertyValue(css) !== hc[k]) hd.style.setProperty(css, hc[k], 'important');
      });
    }
    /* #362 「高速化」の文字の高さをドラフトモードの文字にそろえる（中心どうしの差だけ縦にずらす） */
    var lb = document.querySelector('#accel-lbl .accel-lbl-t');
    if (lb && src.offsetParent) {
      var cur = parseFloat(lb.getAttribute('data-dy') || '0');
      /* ？ が両方にあれば ？ どうし（同じ大きさなので文字の並びも揃う）、無ければ文字の箱どうし */
      var sr = (hs && hd ? hs : src).getBoundingClientRect(), dr = (hs && hd ? hd : lb).getBoundingClientRect();
      var dy = Math.round((sr.top + sr.height / 2) - (dr.top + dr.height / 2) + cur);
      if (Math.abs(dy - cur) >= 1) {
        lb.style.transform = 'translateY(' + dy + 'px)';
        lb.setAttribute('data-dy', String(dy));
      }
    }
  }
  if (!window.__h3AccelSync) { window.__h3AccelSync = setInterval(syncAccel, 800); }
  syncAccel();
  if (window.__h3Help) { place(); return; }
  window.__h3Help = true;
  window.__h3HelpPlace = place;

  var live = null;
  function hide() { if (live) { live.remove(); live = null; } }
  function show(icon) {
    hide();
    var src = icon.querySelector('.h3-tip');
    if (!src) return;
    live = document.createElement('div');
    live.className = 'h3-tip-live';
    live.innerHTML = src.innerHTML;
    document.body.appendChild(live);
    var r = icon.getBoundingClientRect();
    var w = live.offsetWidth, h = live.offsetHeight;
    var left = Math.min(Math.max(8, r.left + r.width / 2 - w / 2),
                        window.innerWidth - w - 8);
    var top = r.bottom + 8;
    if (top + h > window.innerHeight - 8) top = Math.max(8, r.top - h - 8);
    live.style.left = left + 'px';
    live.style.top = top + 'px';
  }
  function icoOf(e) {
    var t = e.target;
    return (t && t.closest) ? t.closest('.h3-help') : null;
  }
  document.addEventListener('mouseover', function (e) { var i = icoOf(e); if (i) show(i); });
  document.addEventListener('mouseout', function (e) { if (icoOf(e)) hide(); });
  document.addEventListener('focusin', function (e) { var i = icoOf(e); if (i) show(i); });
  document.addEventListener('focusout', function (e) { if (icoOf(e)) hide(); });
  document.addEventListener('click', function (e) {
    var i = icoOf(e);
    if (!i) return;
    e.preventDefault();            /* 見出しの中にあるので、開閉やチェックを止める */
    e.stopPropagation();
    show(i);
  }, true);
  window.addEventListener('scroll', hide, true);
  window.addEventListener('resize', hide);

  /* Gradio は部品を作り直すので、増えたぶんを見張って置き直す */
  var timer = null;
  new MutationObserver(function () {
    clearTimeout(timer);
    timer = setTimeout(place, 120);
  }).observe(document.body, {childList: true, subtree: true});
  place();
}
