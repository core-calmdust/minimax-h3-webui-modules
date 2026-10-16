
() => {
  if (window.__h3RmPick) { return; }
  window.__h3RmPick = true;
  var last = {sel: null, t: 0};
  function domSel() {
    var a = [];
    document.querySelectorAll('#refmod-pick .rmp-tile.on').forEach(function (el) {
      a.push([+el.dataset.ord || 9999, el.dataset.rmName]);
    });
    a.sort(function (x, y) { return x[0] - y[0]; });
    return a.map(function (x) { return x[1]; });
  }
  function paint(sel) {
    document.querySelectorAll('#refmod-pick .rmp-tile').forEach(function (el) {
      var i = sel.indexOf(el.dataset.rmName), b = el.querySelector('.rmp-no');
      el.classList.toggle('on', i >= 0);
      el.dataset.ord = i >= 0 ? (i + 1) : 0;
      if (i >= 0) {
        if (!b) { b = document.createElement('span'); b.className = 'rmp-no'; el.appendChild(b); }
        b.textContent = i + 1;
      } else if (b) { b.remove(); }
    });
  }
  function send(sel) {
    var box = document.querySelector('#refmod-pick-act textarea, #refmod-pick-act input');
    if (!box) { return; }
    last = {sel: sel, t: Date.now()};
    paint(sel);
    // 連番は時刻から（ページを読み直しても前より大きい。サーバは古い連番を捨てる）
    window.__h3RmPickSeq = Math.max(Date.now(), (window.__h3RmPickSeq || 0) + 1);
    box.value = JSON.stringify({sel: sel, seq: window.__h3RmPickSeq});
    box.dispatchEvent(new Event('input', {bubbles: true}));
  }
  document.addEventListener('click', function (e) {
    var t = e.target;
    if (!t || !t.closest) { return; }
    if (t.closest('#refmod-pick .rmp-clear')) { send([]); return; }
    var tile = t.closest('#refmod-pick .rmp-tile');
    if (!tile) { return; }
    var base = (last.sel && Date.now() - last.t < 3000) ? last.sel.slice() : domSel();
    var n = tile.dataset.rmName, i = base.indexOf(n);
    if (i >= 0) { base.splice(i, 1); } else { base.push(n); }
    send(base);
  });
}
