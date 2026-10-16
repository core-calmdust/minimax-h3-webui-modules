
() => {
  if (window.__h3Zoom) { return; }
  window.__h3Zoom = true;
  var R = document.documentElement;
  var M = 12;        // 下の余白
  var TOPMIN = 24;   // 上の余白の下限（スクロール中でも押せる帯を残す）

  // ⚠️ 基準は `.gradio-container` ではなく**いま見えているタブの中身**（`.tabitem`）。
  //    container は窓いっぱいなので、それを基準にすると左右に隙間ができない。
  //    タブの中身なら、ふだんの表示と同じ左右の余白がそのまま使える。
  function measure() {
    var base = null;
    var items = document.querySelectorAll('.tabitem');
    for (var i = 0; i < items.length; i++) {
      if (items[i].offsetParent !== null) { base = items[i]; break; }
    }
    if (!base) { base = document.querySelector('.gradio-container') || document.body; }
    var r = base.getBoundingClientRect();
    var top = Math.max(TOPMIN, Math.round(r.top));
    var h = Math.max(240, Math.round(window.innerHeight - top - M));
    R.style.setProperty('--h3-zoom-left', Math.round(r.left) + 'px');
    R.style.setProperty('--h3-zoom-top', top + 'px');
    R.style.setProperty('--h3-zoom-w', Math.max(240, Math.round(r.width)) + 'px');
    R.style.setProperty('--h3-zoom-h', h + 'px');
  }

  // ⚠️ 拡大には2系統ある。
  //    ・`.block.fullscreen` … Gradio の ⛶（一覧・画像）。**閉じるのは必ずボタン経由**
  //    ・`.h3-zoom`          … こちらの自前（動画）。`gr.Video` に fullscreen ボタンが
  //      存在しないため（Gradio 6.26 で確認）。Gradio 側に状態が無いので
  //      クラスの付け外しだけで完結し、「宙に浮く」問題も起きない。
  function open_() { return document.querySelector('.block.fullscreen, .h3-zoom'); }
  function isSelfZoom(f) { return !!(f && f.classList.contains('h3-zoom')); }

  // ⚠️ 閉じるのは**必ず Gradio のボタンを押して**行う。こちらでクラスを外すと
  //    Gradio 側の状態と食い違い、箱が宙に浮いたまま残る（実機で発生）。
  //    ボタンの探し方は3段構え:
  //      1. 開いたときに押されたボタン（覚えてある）
  //      2. 開いている箱の中の icon-button の**最後の1つ**（Gradio は copy → ⛶ の順）
  //    ⚠️ aria-label（"Fullscreen" / "全画面"…）で探すのは**言語で壊れる**ので使わない。
  // ⚠️🔴 **ダウンロードのボタンを押してはいけない。** 実測（Gradio 6.26）:
  //    gr.Image の並びは Fullscreen → Download なので、単純に「最後の1つ」を押すと
  //    ⛶ を閉じるつもりで**ファイルのダウンロードが始まる**（利用者から報告）。
  //    ダウンロード側は `<a download>` に包まれているので、これで確実に見分ける
  //    （aria-label は言語で変わるので使わない）。
  function isDl(b) { return !!(b && b.closest && b.closest('a[download]')); }
  function toggleBtn(f) {
    var b = window.__h3ZoomBtn;
    if (b && f && f.contains(b) && !isDl(b)) { return b; }
    var all = f ? f.querySelectorAll('button.icon-button') : [];
    for (var i = all.length - 1; i >= 0; i--) {
      if (!isDl(all[i])) { return all[i]; }
    }
    return null;
  }

  function close_() {
    var f = open_();
    if (!f) { return; }
    if (isSelfZoom(f)) { f.classList.remove('h3-zoom'); veil(false); return; }
    var b = toggleBtn(f);
    if (b) { b.click(); }
    // 取りこぼしの後始末（`.animating` が残ると宙に浮いたままになる）
    setTimeout(function () {
      var els = document.querySelectorAll('.block.animating');
      for (var i = 0; i < els.length; i++) {
        if (!els[i].classList.contains('fullscreen')) { els[i].classList.remove('animating'); }
      }
    }, 300);
  }

  function veil(on) {
    var v = document.getElementById('h3-zoom-veil');
    if (on) {
      if (!v) {
        v = document.createElement('div');
        v.id = 'h3-zoom-veil';
        v.addEventListener('mousedown', function (e) {
          e.preventDefault(); e.stopPropagation(); close_();
        });
        document.body.appendChild(v);
      }
      v.style.display = 'block';
    } else if (v) { v.style.display = 'none'; }
  }

  // 押されたボタンを覚える（閉じるときに同じものを押す）
  document.addEventListener('click', function (e) {
    var b = e.target && e.target.closest ? e.target.closest('button.icon-button') : null;
    if (b) { window.__h3ZoomBtn = b; }
  }, true);

  // ============================================================
  //  プレビューの拡大（画像・動画とも**自前**）
  // ============================================================
  // ⚠️🔴 **Gradio の ⛶ には乗らない。** 実測で分かったこと:
  //    ・`buttons` に並べた順は表示順にならない（画像は Fullscreen → Download）
  //    ・`gr.Video` には "fullscreen" が**存在しない**（download と share だけ）
  //    ・表示が切り替わると、隠れたほうの部品は DOM ごと消える
  //    部品ごとに違うものへ乗り続けるのは無理なので、`.h3-zoom` を自分で付け外しする。
  //    Gradio 側に状態が無いので「宙に浮く」問題も起きない（一覧の ⛶ は従来どおり）。
  var H3_PREVIEW_OF = {'preview-img': 0, 'preview-video': 0,
                       'lib-preview-img': 1, 'lib-preview-video': 1};

  function previewHost(el) {
    return el && el.closest
      ? el.closest('#preview-img, #preview-video, #lib-preview-img, #lib-preview-video, #upi-out-img')
      : null;
  }

  function zoomOn(h) {
    if (!h || h.classList.contains('h3-zoom')) { return false; }
    h.classList.add('h3-zoom');
    // ⚠️ 入力欄に focus が残っていると、そこが矢印キーを食う。外しておく
    try { if (document.activeElement && document.activeElement.blur) { document.activeElement.blur(); } }
    catch (err) {}
    return true;
  }

  // 画像は1回押しで開閉（再生という用事が無いので）
  document.addEventListener('click', function (e) {
    var t = e.target;
    if (!t || t.tagName !== 'IMG') { return; }
    // ⚠️ `closest('button')` で弾いてはいけない。Gradio は <img> を <button> で包んでいる
    //    （IMG < DIV.image-frame < BUTTON < DIV.image-container。Chromium で実測）
    if (t.closest('button.icon-button') || t.closest('.thumbnail-item')) { return; }
    var h = previewHost(t);
    if (!h || h.id.indexOf('-img') < 0) { return; }
    if (h.classList.contains('h3-zoom')) { h.classList.remove('h3-zoom'); veil(false); }
    else { zoomOn(h); }
  });

  // 動画はダブルクリック（1回押しは再生 / 停止なので奪わない）
  document.addEventListener('dblclick', function (e) {
    var t = e.target;
    if (!t || t.tagName !== 'VIDEO') { return; }
    var h = previewHost(t);
    if (!h) { return; }
    e.preventDefault();
    if (h.classList.contains('h3-zoom')) { h.classList.remove('h3-zoom'); veil(false); }
    else { zoomOn(h); }
  });

  // ---- 前後送り ----------------------------------------------------------
  // 素材の一覧は `button.thumbnail-item`、選択中には `.selected` が付く（実測）。
  // ⚠️ `#batch-strip button` には一覧自身の ⛶ も混ざるので、**必ず `.thumbnail-item` で絞る**。
  document.addEventListener('click', function (e) {
    var g = e.target && e.target.closest
        ? e.target.closest('#batch-strip, #recent-gallery, #lib-grid') : null;
    if (g) { window.__h3Gallery = g.id; }
  }, true);

  function thumbs(el) { return el ? el.querySelectorAll('button.thumbnail-item') : []; }

  function galleryFor(hostId) {
    if (H3_PREVIEW_OF[hostId] === 1) { return document.getElementById('lib-grid'); }
    var ids = [window.__h3Gallery, 'batch-strip', 'recent-gallery'];
    for (var i = 0; i < ids.length; i++) {
      if (!ids[i] || ids[i] === 'lib-grid') { continue; }
      var g = document.getElementById(ids[i]);
      if (g && thumbs(g).length > 1) { return g; }
    }
    return null;
  }

  function curIndex(items) {
    for (var i = 0; i < items.length; i++) {
      if (items[i].classList.contains('selected')) { return i; }
    }
    return 0;
  }

  // 表示が切り替わると部品が入れ替わるので、拡大を新しいほうへ移し替える
  function carry(side, tries) {
    if (open_()) { return; }
    var ids = side === 1 ? ['lib-preview-img', 'lib-preview-video']
                         : ['preview-img', 'preview-video'];
    for (var i = 0; i < ids.length; i++) {
      var h = document.getElementById(ids[i]);
      if (h && (h.querySelector('img') || h.querySelector('video'))) { zoomOn(h); return; }
    }
    if ((tries || 0) < 6) { setTimeout(function () { carry(side, (tries || 0) + 1); }, 180); }
  }

  // ⚠️ **1回の送りごとにサーバへ往復する**（Gradio の select → Python → 画像の取り直し）。
  //    1920×1088 の PNG だと数MBになるので、素早く連打されたぶんを全部投げると詰まる。
  //    まとめて**最後の位置にだけ**跳ぶ。
  var H3_STEP = {pending: null, timer: null};

  function commitStep() {
    H3_STEP.timer = null;
    var p = H3_STEP.pending;
    H3_STEP.pending = null;
    if (!p) { return; }
    var items = thumbs(p.gallery);
    if (p.index < 0 || p.index >= items.length) { return; }
    items[p.index].click();
    setTimeout(function () { carry(p.side, 0); }, 240);
  }

  function stepPreview(dir) {
    var f = open_();
    if (!f || !(f.id in H3_PREVIEW_OF)) { return false; }
    var g = galleryFor(f.id);
    var items = thumbs(g);
    if (items.length < 2) { return false; }
    var base = H3_STEP.pending ? H3_STEP.pending.index : curIndex(items);
    var next = base + dir;
    if (next < 0 || next >= items.length) { return false; }
    H3_STEP.pending = {gallery: g, index: next, side: H3_PREVIEW_OF[f.id]};
    if (H3_STEP.timer) { clearTimeout(H3_STEP.timer); }
    H3_STEP.timer = setTimeout(commitStep, 90);
    navSync();
    return true;
  }

  // ---- 前後送りのボタン（幕より前に出すので画像の上でも押せる）--------------
  function navEl() {
    var n = document.getElementById('h3-zoom-nav');
    if (n) { return n; }
    n = document.createElement('div');
    n.id = 'h3-zoom-nav';
    [['prev', '‹', -1], ['next', '›', 1]].forEach(function (spec) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'h3-zoom-arrow h3-zoom-' + spec[0];
      b.textContent = spec[1];
      b.setAttribute('aria-label', spec[0] === 'prev' ? 'Previous' : 'Next');
      b.addEventListener('click', function (e) {
        e.preventDefault(); e.stopPropagation(); stepPreview(spec[2]);
      });
      n.appendChild(b);
    });
    document.body.appendChild(n);
    return n;
  }

  function navSync() {
    var f = open_();
    var n = document.getElementById('h3-zoom-nav');
    if (!f || !(f.id in H3_PREVIEW_OF)) { if (n) { n.style.display = 'none'; } return; }
    var items = thumbs(galleryFor(f.id));
    if (items.length < 2) { if (n) { n.style.display = 'none'; } return; }
    n = navEl();
    n.style.display = 'block';
    var i = H3_STEP.pending ? H3_STEP.pending.index : curIndex(items);
    n.querySelector('.h3-zoom-prev').disabled = (i <= 0);
    n.querySelector('.h3-zoom-next').disabled = (i >= items.length - 1);
  }

  document.addEventListener('keydown', function (e) {
    if (!open_()) { return; }
    if (e.key === 'Escape') { e.preventDefault(); close_(); return; }
    // ⚠️ 拡大中は矢印を**必ず**こちらで受ける。入力欄に focus が残っていると
    //    スライダーが動いてしまうので、ここで止める（開いた時点で blur もしている）
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault();
      stepPreview(e.key === 'ArrowRight' ? 1 : -1);
    }
  });
  function sync() {
    if (open_()) { measure(); veil(true); navSync(); return; }
    veil(false);
    navSync();
    // ボタンで直接閉じたときの取りこぼしもここで拾う
    clearTimeout(window.__h3ZoomTidy);
    window.__h3ZoomTidy = setTimeout(function () {
      var els = document.querySelectorAll('.block.animating');
      for (var i = 0; i < els.length; i++) {
        if (!els[i].classList.contains('fullscreen')) { els[i].classList.remove('animating'); }
      }
    }, 300);
  }
  window.addEventListener('resize', sync);
  window.addEventListener('scroll', sync, true);
  // `.fullscreen` が付いた/外れたのを見張る（Gradio が付け外しする）
  new MutationObserver(sync).observe(document.body,
      {subtree: true, attributes: true, attributeFilter: ['class']});
  sync();
}
