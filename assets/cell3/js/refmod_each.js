
() => {
  if (window.__h3RmEach) { return; }
  window.__h3RmEach = true;
  document.addEventListener('input', function (e) {
    var t = e.target; if (!t || !t.matches || !t.matches('#refmod-info .rm-each input[type=range]')) { return; }
    var v = t.parentNode.querySelector('.rm-each-v'); if (v) { v.textContent = Number(t.value).toFixed(2); }
  });
  document.addEventListener('change', function (e) {
    var t = e.target; if (!t || !t.matches || !t.matches('#refmod-info .rm-each input[type=range]')) { return; }
    var box = document.querySelector('#refmod-each textarea, #refmod-each input'); if (!box) { return; }
    window.__h3RmEachSeq = (window.__h3RmEachSeq || 0) + 1;
    box.value = t.dataset.rmName + '|' + t.value + '|' + window.__h3RmEachSeq;
    box.dispatchEvent(new Event('input', {bubbles: true}));
  });
}
