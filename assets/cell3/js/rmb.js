
() => {
  if (window.__h3Rmb) { return; }
  window.__h3Rmb = true;
  function send(v) {
    var box = document.querySelector('#rmb-act textarea, #rmb-act input');
    if (!box) { return; }
    window.__h3RmbSeq = (window.__h3RmbSeq || 0) + 1;
    box.value = v + '|' + window.__h3RmbSeq;
    box.dispatchEvent(new Event('input', {bubbles: true}));
  }
  function fileUrl(p) {
    var root = (window.gradio_config && window.gradio_config.root) || '';
    return root.replace(/\/$/, '') + '/gradio_api/file=' + encodeURI(p);
  }
  function closeZoom() { var z = document.getElementById('rmb-zoom'); if (z) { z.remove(); } }
  function openZoom(cell) {
    closeZoom();
    var kind = cell.dataset.kind, src = cell.dataset.src, th = cell.dataset.thumb;
    var z = document.createElement('div'); z.id = 'rmb-zoom';
    var el;
    if (kind === 'video' && src) { el = document.createElement('video'); el.src = fileUrl(src); el.controls = true; el.autoplay = true; el.loop = true; }
    else if (kind === 'audio' && src) { el = document.createElement('audio'); el.src = fileUrl(src); el.controls = true; el.autoplay = true; }
    else { el = document.createElement('img'); el.src = (kind === 'image' && src) ? fileUrl(src) : th; if (kind === 'image' && th) { el.onerror = function () { el.src = th; }; } }
    el.addEventListener('click', function (e) { e.stopPropagation(); });
    z.appendChild(el);
    var x = document.createElement('button'); x.type = 'button'; x.className = 'rmb-zoom-x'; x.textContent = '✕';
    z.appendChild(x);
    z.addEventListener('click', closeZoom);
    document.body.appendChild(z);
  }
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') { closeZoom(); } });
  document.addEventListener('click', function (e) {
    var t = e.target; if (!t || !t.closest) { return; }
    var cell = t.closest('#rmb-list .rmb-cell'); if (!cell) { return; }
    if (t.closest('.rmb-full')) { e.preventDefault(); openZoom(cell); }
    else if (t.closest('.rmb-del')) { e.preventDefault(); send('del|' + cell.dataset.i); }
  });
  document.addEventListener('dblclick', function (e) {
    var t = e.target; if (!t || !t.closest || t.closest('.rmb-ops')) { return; }
    var cell = t.closest('#rmb-list .rmb-cell'); if (cell) { openZoom(cell); }
  });
  var dragI = null, dragK = null;
  function clr() { document.querySelectorAll('#rmb-list .rmb-over').forEach(function (n) { n.classList.remove('rmb-over'); }); }
  document.addEventListener('dragstart', function (e) {
    var cell = e.target && e.target.closest && e.target.closest('#rmb-list .rmb-cell'); if (!cell) { return; }
    dragI = cell.dataset.i; dragK = cell.dataset.kind; cell.classList.add('rmb-dragging');
    try { e.dataTransfer.setData('text/plain', 'rmb'); e.dataTransfer.effectAllowed = 'move'; } catch (err) {}
  });
  document.addEventListener('dragend', function (e) {
    var cell = e.target && e.target.closest && e.target.closest('#rmb-list .rmb-cell');
    if (cell) { cell.classList.remove('rmb-dragging'); } clr(); dragI = null;
  });
  document.addEventListener('dragover', function (e) {
    if (dragI === null) { return; }
    var cell = e.target && e.target.closest && e.target.closest('#rmb-list .rmb-cell');
    if (!cell || cell.dataset.kind !== dragK) { return; }
    e.preventDefault(); clr(); cell.classList.add('rmb-over');
  });
  document.addEventListener('drop', function (e) {
    if (dragI === null) { return; }
    var cell = e.target && e.target.closest && e.target.closest('#rmb-list .rmb-cell');
    if (!cell || cell.dataset.kind !== dragK) { return; }
    e.preventDefault(); clr();
    if (cell.dataset.i !== dragI) { send('mv|' + dragI + '|' + cell.dataset.i); }
    dragI = null;
  });
}
