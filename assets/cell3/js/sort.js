
() => {
  if (window.__h3Sort) { return; }
  window.__h3Sort = true;
  var MAP = {'lora-table': 'lora-sort', 'cl-table': 'cl-sort', 'rmm-table': 'rmm-sort'};

  function owner(el) {
    var n = el;
    while (n) {
      if (n.id && MAP[n.id]) { return n.id; }
      n = n.parentElement;
    }
    return null;
  }

  function onHead(e) {
    var t = e.target;
    if (!t || !t.closest) { return; }
    // ⚠️ 見出しの**枠全体**で拾う。`.header-content` は文字の幅しかなく、余白を押すと
    //    書き換えられる列（REFMOD の名前・フォルダ、LORA のトリガー）では見出しが入力状態になって
    //    並べ替えにならなかった（実機 2026-09-29。Gradio 6.27 で再現・確認）。
    //    除外するのは列メニュー（⋮）と列幅のつまみだけ
    var th = t.closest('thead th');
    if (!th) { return; }
    if (t.closest('.cell-menu-button') || t.closest('[class*="resize"]')) { return; }
    var id = owner(th);
    if (!id) { return; }
    e.preventDefault();
    e.stopPropagation();
    if (e.type !== 'click') { return; }        // dblclick は潰すだけ
    var idx = Array.prototype.indexOf.call(th.parentElement.children, th);
    if (idx < 0) { return; }
    var box = document.querySelector('#' + MAP[id] + ' textarea, #' + MAP[id] + ' input');
    if (!box) { return; }
    window.__h3SortSeq = (window.__h3SortSeq || 0) + 1;
    box.value = idx + '|' + window.__h3SortSeq;
    box.dispatchEvent(new Event('input', {bubbles: true}));
  }

  // ⚠️ **大きく開いている（`.fullscreen`）あいだは、表に文字を入れさせない。**
  //    大きく開くのは「見るため」で、後ろは幕で隠れているから直しても確かめられない。
  //    ダブルクリックを潰すだけでは取りこぼす道（キー操作など）があるので、
  //    **入力欄に焦点が入ったら外す**方も入れてある（これが最後の砦）。
  function inZoomedTable(el) {
    if (!el || !el.closest) { return false; }
    var fs = el.closest('.block.fullscreen');
    return !!(fs && MAP[fs.id]);
  }

  document.addEventListener('dblclick', function (e) {
    if (inZoomedTable(e.target)) { e.preventDefault(); e.stopPropagation(); }
  }, true);

  document.addEventListener('focusin', function (e) {
    var t = e.target;
    if (!inZoomedTable(t)) { return; }
    if (t.tagName === 'TEXTAREA' || t.tagName === 'INPUT' || t.isContentEditable) {
      t.blur();
    }
  }, true);

  document.addEventListener('click', onHead, true);
  document.addEventListener('dblclick', onHead, true);
}
