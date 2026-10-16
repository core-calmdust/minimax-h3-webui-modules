
() => {
  // 🔴 パディングを計算するのではなく、**タブのバーそのものの実寸に合わせる**。
  //    Gradio の版によって「どこに padding が入るか」が変わるので、
  //    合わせたい相手の矩形を直接測るほうが確実（2026-09-02 / 計算方式は外した）。
  function bar() {
    var c = ['.tab-nav', '[role="tablist"]', '.tabs > div:first-child'];
    for (var i = 0; i < c.length; i++) {
      var e = document.querySelector(c[i]);
      if (e && e.getBoundingClientRect().width > 0) return e;
    }
    return null;
  }
  function fit() {
    var el = document.getElementById('app-cred');
    var nav = bar();
    if (!el || !nav) return;
    var a = el.getBoundingClientRect(), b = nav.getBoundingClientRect();
    if (!a.width || !b.width) return;
    el.style.setProperty('--cred-bleed', Math.max(0, a.left - b.left) + 'px');
    el.style.setProperty('--cred-bleed-r', Math.max(0, b.right - a.right) + 'px');
  }
  fit();
  // ⚠️ SYSTEM タブは**開くまで描かれない**。300ms×10 では間に合わないことがある
  //    （実際に合わなかった）。タブのクリックと DOM の変化にも反応させる。
  window.addEventListener('resize', fit);
  document.addEventListener('click', function () { setTimeout(fit, 60); }, true);
  try {
    new MutationObserver(function () {
      if (window.__credT) { return; }
      window.__credT = setTimeout(function () { window.__credT = 0; fit(); }, 120);
    }).observe(document.body, {childList: true, subtree: true});
  } catch (e) {}
  var n = 0;
  var t = setInterval(function () { fit(); if (++n > 60) clearInterval(t); }, 500);
}
