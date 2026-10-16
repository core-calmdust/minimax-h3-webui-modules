
() => {
  if (window.__h3RmmMulti) { return; }
  window.__h3RmmMulti = true;
  function items(g) { return Array.from(g.querySelectorAll('.thumbnail-item')); }
  function clear(g) {
    g.classList.remove('rmm-multi-on');
    items(g).forEach(function (el) { el.classList.remove('rmm-multi'); });
  }
  function send(idx) {
    var box = document.querySelector('#rmm-multi-act textarea, #rmm-multi-act input');
    if (!box) { return; }
    window.__h3RmmSeq = Math.max(Date.now(), (window.__h3RmmSeq || 0) + 1);
    box.value = JSON.stringify({idx: idx, seq: window.__h3RmmSeq});
    box.dispatchEvent(new Event('input', {bubbles: true}));
  }
  document.addEventListener('click', function (e) {
    var t = e.target;
    if (!t || !t.closest) { return; }
    var it = t.closest('#rmm-gallery .thumbnail-item');
    if (!it) {
      // 🆕 複数選択中に FINDER のアイコン以外を押したら解除（右の操作欄＝CREATE で使う・削除などは除く）。
      //    選択は空になるので、Gradio の .selected（1 件）の枠も消しておく（rmm-cleared）
      var g0 = document.querySelector('#rmm-gallery.rmm-multi-on');
      if (g0 && t.closest('#rmm-finder') && !t.closest('#rmm-right')) {
        clear(g0); g0.classList.add('rmm-cleared'); send([]);
      }
      return;
    }
    var g = it.closest('#rmm-gallery');
    g.classList.remove('rmm-cleared');
    if (!(e.metaKey || e.ctrlKey)) { clear(g); return; }
    e.preventDefault(); e.stopPropagation();
    var all = items(g);
    if (!g.classList.contains('rmm-multi-on')) {
      all.forEach(function (el) { if (el.classList.contains('selected')) { el.classList.add('rmm-multi'); } });
      g.classList.add('rmm-multi-on');
    }
    it.classList.toggle('rmm-multi');
    var idx = [];
    all.forEach(function (el, i) { if (el.classList.contains('rmm-multi')) { idx.push(i); } });
    send(idx);
  }, true);
}
