
() => {
  if (window.__h3TagDbl) { return; }
  window.__h3TagDbl = true;
  var RE = /^ref-slot-(image|video|audio)-([0-9]+)$/;
  var LAB = {image: 'Picture', video: 'Video', audio: 'Audio'};
  function box() { return document.querySelector('#main-prompt textarea'); }
  document.addEventListener('focusin', function (e) {
    var b = box();
    if (b && e.target === b) { b.__h3Touched = true; }
  });
  document.addEventListener('dblclick', function (e) {
    var t = e.target;
    if (!t || !t.closest) { return; }
    var tag = '', el = null;
    var rm = t.closest('#refmod-info [data-h3-tag]');
    if (rm) {
      tag = rm.getAttribute('data-h3-tag') || ''; el = rm.querySelector('img, .rm-noimg') || rm;
    } else {
      var slot = t.closest('[id^="ref-slot-"]');
      if (!slot || t.closest('button')) { return; }
      var m = RE.exec(slot.id);
      if (!m || slot.offsetParent === null) { return; }
      tag = '<' + LAB[m[1]] + ' ' + (+m[2] + 1) + '>'; el = slot;
    }
    var b = box();
    if (!tag || !b) { return; }
    e.preventDefault();
    try { window.getSelection().removeAllRanges(); } catch (err) {}
    var v = b.value || '';
    // もう入っているラベルなら**消す**（ダブルクリックで入れ／外しを切り替え。LoRA 一覧のクリックと同じ考え方）。
    // 前後のスペースは 1 つだけ残す（両側にあれば 1 つ、片側だけなら 0）
    var esc = tag.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    var re = new RegExp('( ?)' + esc + '( ?)', 'g');
    if (v.indexOf(tag) >= 0) {
      b.value = v.replace(re, function (_m, a1, a2) { return (a1 && a2) ? ' ' : ''; });
      b.__h3Touched = true;
      b.dispatchEvent(new Event('input', {bubbles: true}));
      if (el) {
        el.classList.add('h3-tag-flash');
        setTimeout(function () { el.classList.remove('h3-tag-flash'); }, 450);
      }
      return;
    }
    var s0 = b.__h3Touched ? b.selectionStart : v.length;
    var s1 = b.__h3Touched ? b.selectionEnd : v.length;
    if (s0 == null) { s0 = s1 = v.length; }
    var pre = v.slice(0, s0), post = v.slice(s1);
    var ins = tag;
    if (pre && !/\s$/.test(pre)) { ins = ' ' + ins; }
    if (post && !/^\s/.test(post)) { ins = ins + ' '; }
    b.value = pre + ins + post;
    var c = (pre + ins).length;
    b.__h3Touched = true;
    try { b.setSelectionRange(c, c); } catch (err) {}
    b.dispatchEvent(new Event('input', {bubbles: true}));
    if (el) {
      el.classList.add('h3-tag-flash');
      setTimeout(function () { el.classList.remove('h3-tag-flash'); }, 450);
    }
  });
}
