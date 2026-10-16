
() => {
  var RE = /^ref-slot-(image|video|audio)-([0-9]+)$/;
  function info(id) { var m = RE.exec(id || ''); return m ? {kind: m[1], idx: +m[2]} : null; }
  function clearMarks() {
    var els = document.querySelectorAll('.ref-drag-over');
    for (var i = 0; i < els.length; i++) { els[i].classList.remove('ref-drag-over'); }
  }
  function setup() {
    var slots = document.querySelectorAll('[id^="ref-slot-"]');
    for (var i = 0; i < slots.length; i++) {
      (function (el) {
        // ⚠️ 中の画像・動画は **draggable="false"** にする。既定のままだと
        //    ブラウザが「画像そのもののドラッグ」を始めてしまい、スロットの
        //    並べ替えにならないうえ、落とした先で画像を開く動作が起きる。
        //    （Keyframe 側は最初からこうしてあるので問題が出ていない）
        //    ⚠️ 中身は差し替わるので、**毎回**付け直す（下の重複防止の外に置く）
        var med = el.querySelectorAll('img, video, a:not([download])');
        for (var k = 0; k < med.length; k++) { med[k].setAttribute('draggable', 'false'); }
        if (el.__h3dnd) { return; }
        el.__h3dnd = true;
        el.setAttribute('draggable', 'true');
        // 画像そのものを押したときの Gradio 側の動作（拡大など）は止める。
        // 道具箱のボタン（⛶ / ⬇）は `.icon-button` なので、そちらは素通しする
        el.addEventListener('click', function (e) {
          var t = e.target;
          if (!t || !t.closest) { return; }
          if (t.closest('button.icon-button') || t.closest('.ref-btn')) { return; }
          var b = t.closest('button');
          if (b && el.contains(b)) { e.preventDefault(); e.stopPropagation(); }
        }, true);
        el.addEventListener('dragstart', function (e) {
          var a = info(el.id);
          if (!a) { return; }
          try {
            e.dataTransfer.setData('text/plain', el.id);
            e.dataTransfer.effectAllowed = 'move';
          } catch (err) {}
          el.classList.add('ref-dragging');
        });
        el.addEventListener('dragend', function () {
          el.classList.remove('ref-dragging'); clearMarks();
        });
        el.addEventListener('dragover', function (e) {
          e.preventDefault();
          try { e.dataTransfer.dropEffect = 'move'; } catch (err) {}
          el.classList.add('ref-drag-over');
        });
        el.addEventListener('dragleave', function () { el.classList.remove('ref-drag-over'); });
        el.addEventListener('drop', function (e) {
          e.preventDefault();
          el.classList.remove('ref-drag-over');
          var srcId = '';
          try { srcId = e.dataTransfer.getData('text/plain'); } catch (err) {}
          var a = info(srcId), b = info(el.id);
          if (!a || !b || a.kind !== b.kind || a.idx === b.idx) { return; }
          var box = document.querySelector('#ref-dnd textarea, #ref-dnd input');
          if (!box) { return; }
          window.__h3RefSeq = (window.__h3RefSeq || 0) + 1;
          box.value = a.kind + '|' + a.idx + '|' + b.idx + '|' + window.__h3RefSeq;
          box.dispatchEvent(new Event('input', {bubbles: true}));
        });
      })(slots[i]);
    }
  }
  setup();
  if (!window.__h3RefObs) {
    window.__h3RefObs = new MutationObserver(function () {
      clearTimeout(window.__h3RefTimer);
      window.__h3RefTimer = setTimeout(setup, 120);
    });
    window.__h3RefObs.observe(document.body, {childList: true, subtree: true});
  }
}
