
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
