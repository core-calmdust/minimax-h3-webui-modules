
  window.__h3GradioTexts = __TABLE__;
  window.__h3GradioSweep = function () {
    // ⚠️ **辞書は毎回組み直す。** 一度作って閉じ込めると、言語を変えたあとに
    //    Gradio が再描画したときに古い言語で当ててしまう（実際にそれで直らなかった）。
    var lang = window.__h3Lang || 'ja';
    var tbl = window.__h3GradioTexts || [], map = {};
    for (var i = 0; i < tbl.length; i++) {
      var row = tbl[i], to = row[lang] || row.ja;
      for (var k in row) { if (row[k] && row[k] !== to) { map[row[k]] = to; } }
    }
    var SKIP = {TEXTAREA: 1, INPUT: 1, SCRIPT: 1, STYLE: 1, CODE: 1, PRE: 1};
    try {
      var w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT), hits = [];
      while (w.nextNode()) {
        var n = w.currentNode;
        if (!n.parentElement || SKIP[n.parentElement.tagName]) { continue; }
        var t = n.textContent.trim();
        if (t && map[t]) { hits.push([n, t, map[t]]); }
      }
      for (var j = 0; j < hits.length; j++) {
        hits[j][0].textContent = hits[j][0].textContent.replace(hits[j][1], hits[j][2]);
      }
    } catch (e) {}
  };
  window.__h3GradioText = function (lang) {
    if (lang) { window.__h3Lang = lang; }
    window.__h3GradioSweep();
    if (!window.__h3GradioObs) {
      // Gradio が描き直すと元の文言に戻るので、**描き直しのたびに当て直す**
      window.__h3GradioObs = new MutationObserver(function () {
        clearTimeout(window.__h3GradioTimer);
        window.__h3GradioTimer = setTimeout(window.__h3GradioSweep, 100);
      });
      window.__h3GradioObs.observe(document.body, {childList: true, subtree: true});
    }
  };
