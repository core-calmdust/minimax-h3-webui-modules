
() => {
  if (window.__h3LibNav) return;
  window.__h3LibNav = true;

  function box() { return document.querySelector('#lib-preview-box'); }
  function thumbs() {
    var g = document.querySelector('#lib-grid');
    if (!g) return [];
    var l = g.querySelectorAll('button.thumbnail-item');
    if (!l.length) l = g.querySelectorAll('.grid-container button');
    return Array.prototype.slice.call(l);
  }
  function selIndex(items) {
    for (var i = 0; i < items.length; i++)
      if (items[i].classList.contains('selected')) return i;
    return -1;
  }
  function sig(items) {
    return items.map(function (b) {
      var im = b.querySelector('img'); return im ? im.src : '';
    }).join('|');
  }
  function afterPage(before, pick) {
    var tries = 0;
    (function poll() {
      var items = thumbs();
      if (items.length && sig(items) !== before) {
        var t = (pick === 'first') ? items[0] : items[items.length - 1];
        if (t) t.click();
        return;
      }
      if (++tries > 60) return;            /* 最大およそ4秒待って諦める */
      setTimeout(poll, 60);
    })();
  }
  /* 全画面のまま移動したとき、Gradio がプレビューの箱ごと作り直すと
     全画面の対象が DOM から消えて解除される。**キー操作の直後は
     ユーザー操作とみなされる**うちに、新しい箱へ入れ直す */
  function keepFs() {
    var tries = 0;
    (function poll() {
      if (document.fullscreenElement) return;    /* まだ全画面 */
      var b = box();
      if (b && b.requestFullscreen) { b.requestFullscreen().catch(function () {}); return; }
      if (++tries > 30) return;
      setTimeout(poll, 60);
    })();
  }
  function nav(dir) {
    var items = thumbs();
    if (!items.length) return;
    var wasFs = !!document.fullscreenElement;
    var after = wasFs ? keepFs : function () {};
    var i = selIndex(items);
    if (i < 0) { items[0].click(); after(); return; }   /* 未選択なら先頭から */
    var j = i + (dir === 'next' ? 1 : -1);
    if (j >= 0 && j < items.length) { items[j].click(); after(); return; }
    var pb = document.querySelector(dir === 'next' ? '#lib-next-page' : '#lib-prev-page');
    if (!pb || pb.disabled) return;              /* 端のページ */
    var before = sig(items);
    pb.click();
    afterPage(before, dir === 'next' ? 'first' : 'last');
    after();
  }

  /* ---- 全画面 ---- */
  function inBox(el) { var b = box(); return !!(b && el && (el === b || b.contains(el))); }
  function toggleFs() {
    var b = box();
    if (!b) return;
    if (document.fullscreenElement) document.exitFullscreen();
    else if (b.requestFullscreen) b.requestFullscreen().catch(function () {});
  }
  /* 全画面が <video> に付くと、次のファイルへ移った瞬間に Gradio が中身を
     作り直して全画面が解ける。**全画面は必ず箱に付ける**。
     ここではブラウザ標準のコントロールが出た場合の全画面ボタンだけ止めておく
     （Gradio 独自プレーヤーのボタンは下の click 横取りで受ける） */
  function ensureUi() {
    var b = box();
    if (!b) return;
    b.querySelectorAll('video').forEach(function (v) {
      if (v.getAttribute('controlsList') !== 'nofullscreen')
        v.setAttribute('controlsList', 'nofullscreen');
    });
  }
  /* ⚠️ Gradio のプレーヤーは**独自の全画面ボタン**（`[aria-label="full-screen"]`）を
     持っていて、これは `controlsList` では消せない。押されると中の要素が全画面に
     なり、次のファイルへ移った瞬間に解ける。**押下を横取りして箱の全画面にする** */
  document.addEventListener('click', function (e) {
    var t = e.target, b = box();
    if (!t || !t.closest || !b) return;
    var g = t.closest('[aria-label="full-screen"]');
    if (!g || !b.contains(g)) return;
    e.preventDefault();
    e.stopPropagation();
    toggleFs();
  }, true);

  /* それでも中の要素が全画面になったときの保険。
     ⚠️ **一度抜いてから入れ直してはいけない。** 入れ直しがブラウザに拒否されて
        「一瞬だけ全画面」になる（実機で発生）。抜かずに親へ要求すれば入れ替わり、
        失敗しても元の全画面がそのまま残る */
  document.addEventListener('fullscreenchange', function () {
    var el = document.fullscreenElement, b = box();
    if (el && b && el !== b && b.contains(el) && b.requestFullscreen)
      b.requestFullscreen().catch(function () {});
  });

  document.addEventListener('keydown', function (e) {
    /* ⚠️ 「箱が全画面か」で判定すると、箱が作り直された直後に取りこぼす。
       **何かが全画面なら**前後移動を優先する（LIBRARY を開いている前提） */
    var fsAny = !!document.fullscreenElement;
    var t = e.target || {};
    var tag = (t.tagName || '').toUpperCase();
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || t.isContentEditable) return;
    var grid = document.querySelector('#lib-grid');
    if (!grid || (!fsAny && !grid.offsetParent)) return;   /* LIBRARYタブが開いていない */
    if (e.key === 'f' || e.key === 'F') { e.preventDefault(); toggleFs(); return; }
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    /* 通常表示のときはプレーヤーのシーク操作を邪魔しない。全画面では前後移動を優先する */
    if (!fsAny && tag === 'VIDEO') return;
    e.preventDefault();
    nav(e.key === 'ArrowRight' ? 'next' : 'prev');
  }, true);

  /* Gradio がプレビューを作り直すたびに ⛶ と controlsList を付け直す */
  var t2 = null;
  new MutationObserver(function () {
    clearTimeout(t2);
    t2 = setTimeout(ensureUi, 150);
  }).observe(document.body, {childList: true, subtree: true});
  ensureUi();
}
