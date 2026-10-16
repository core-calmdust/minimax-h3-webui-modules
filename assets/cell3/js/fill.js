
() => {
  const upd = (r) => {
    const min = +r.min || 0, max = (+r.max || 100), v = +r.value;
    const pct = max === min ? 0 : (v - min) / (max - min) * 100;
    r.style.setProperty('--fill', pct + '%');
  };
  const scan = () => document.querySelectorAll('input[type="range"]').forEach(upd);
  document.addEventListener('input', (e) => {
    if (e.target && e.target.type === 'range') upd(e.target);
  }, true);
  new MutationObserver(scan).observe(document.body, {childList: true, subtree: true});
  scan();
  setInterval(scan, 400);

  // Cmd/Ctrl + Enter で生成を開始
  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && (e.key === 'Enter' || e.keyCode === 13)) {
      const b = document.querySelector('#generate-btn');
      if (b && !b.disabled) { e.preventDefault(); e.stopPropagation(); b.click(); }
    }
  }, true);
}
