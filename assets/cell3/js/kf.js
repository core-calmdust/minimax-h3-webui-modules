
() => {
  /* 2026-09-15: タイムライン式に作り替え。
     ・アイコンは pointer イベントで動かす（HTML5 DnD は使わない: Gradio が window でドラッグ系を握るため）。
     ・箱の外（上下に track の高さぶん以上）へ出して離すと削除。出している間は赤く沈めて × を重ね、箱の下に帯を出す。
     ・クリック（動かさずに離す）で選択。
     ・track へ画像ファイルをドロップすると、その位置に読み込む（FileReader → data URL → #kf-sync）。
     ・PREVIEW の <video> / <img> の src を 16:9 の箱へ写す（MutationObserver）。無ければ選択中の静止画。
     ⚠️🔴 かつてここに placeSwitch() があった（ON/OFF をタブの見出しへ**移す**仕掛け）。Gradio がナビを描き直すと
        本物の部品ごと消えた（2026-08-29）。**フレームワークが描き直す場所へ本物の部品を移さない。** */
  if (window.__h3Kf2) { return; }
  window.__h3Kf2 = true;

  /* 🔴 2026-09-15 「アイコンが時々消える」対策 2: 操作は**1 つずつ**送る。
     前の操作の返事（Python の描き直し）が来る前に次を送ると、Gradio は次の操作の入力（kf_state）を
     **送った時点の古い値**で集めるので、前の操作の結果（追加した 1 枚・動かした位置）が上書きで消える。
     → 送信待ちの列を持ち、#kf-list が描き直された（data-rev が変わった）のを見てから次を送る。3 秒で保険解除 */
  var sendQ = [], inflight = null, inflightTimer = null;
  /* 🔴 2026-09-16 「激しく動かすと位置が飛ぶ・アイコンが一瞬消える」対策（利用者報告）:
       ① 同じコマの pos / sel が列に溜まったら**最後の 1 つに畳む**（古い意図を送っても描き直しの往復が増えるだけ）。
       ② 未反映の pos は `pending` に持ち、描き直しのたびに**新しい DOM へ掛け直す**（前の操作の返事が来て
          古い位置で描き直されても、画面は最新の意図を保つ。サーバーが追いつけば同じ絵になる）。
       ③ 保険解除は 3 s → 6 s（早すぎると同時実行になり、state の読み合いで直前の操作が消える）。 */
  var pending = {};                             // data-i → 未反映の pos
  function curRev() { var r = tl(); return r ? (r.dataset.rev || '') : ''; }
  function applyPending() {
    var keys = Object.keys(pending); if (!keys.length) { return; }
    var root = tl(); var dur = root ? (parseFloat(root.dataset.dur || '5') || 5) : 5;
    keys.forEach(function (k) {
      var ic = document.querySelector('#kf-list .kf-ic[data-i="' + k + '"]'); if (!ic) { return; }
      var pos = pending[k];
      /* 🔴 MutationObserver（childList 監視）の中から呼ばれる。textContent は同じ文字でも書けば childList 変化に
           なり、観測 → ここ → 書き込み → 観測… の無限ループでページが固まる（2026-09-16 実機「ページが応答しません」）。
           **値が違うときだけ書く**（syncSummary と同じ流儀）。left は style 属性で監視外だが同様に守る */
      if (ic.dataset.kfPend !== String(pos)) { ic.dataset.kfPend = String(pos); ic.style.left = leftCss(pos); }
      var lab = ic.querySelector('.kf-ic-t'); var txt = (pos * dur).toFixed(1) + 's';
      if (lab && lab.textContent !== txt) { lab.textContent = txt; }
    });
  }
  function pendingDone(op) {                    // op の返事が来た → 同じコマの新しい pos が列に無ければ pending を外す
    if (!op || op.op !== 'pos') { return; }
    for (var q = 0; q < sendQ.length; q++) { if (sendQ[q].op === 'pos' && sendQ[q].i === op.i) { return; } }
    delete pending[op.i];
  }
  function rawSend(op) {
    var box = document.querySelector('#kf-sync textarea, #kf-sync input');
    if (!box) { return false; }
    window.__h3KfSeq = (window.__h3KfSeq || 0) + 1;
    op.seq = window.__h3KfSeq;
    box.value = JSON.stringify(op);
    box.dispatchEvent(new Event('input', {bubbles: true}));
    return true;
  }
  function pump() {
    if (inflight || !sendQ.length) { return; }
    var op = sendQ.shift();
    inflight = {rev: curRev(), op: op};
    if (!rawSend(op)) { inflight = null; return; }
    clearTimeout(inflightTimer);
    inflightTimer = setTimeout(function () { inflight = null; pendingDone(op); pump(); }, 6000);   // 返事が来なくても詰まらせない
  }
  function send(op) {
    if (op.op === 'pos' || op.op === 'sel') {   // 同じコマの古い pos / sel を畳む
      sendQ = sendQ.filter(function (q) { return !((q.op === 'pos' || q.op === 'sel') && q.i === op.i); });
    }
    if (op.op === 'pos') { pending[op.i] = op.pos; }
    if (op.op === 'del') { pendingDel[op.i] = true; }
    if (op.op === 'del' || op.op === 'drop') { pending = {}; }   // 添字が変わる操作の後は掛け直さない
    sendQ.push(op); pump();
  }
  var lastRev = '';
  function onRerender() {                       // #kf-list が描き直された → 次の操作へ
    if (inflight && curRev() !== inflight.rev) {
      clearTimeout(inflightTimer); var done = inflight.op; inflight = null; pendingDone(done); pump();
    }
    if (curRev() !== lastRev) { lastRev = curRev(); pendingDel = {}; healIcons('rerender'); }
    rebindDrag();
    applyPending();
  }
  /* 🔍 2026-09-16 「動画を読み込んだ状態でアイコンを動かすと、もう片方が消える（次の操作で戻る）」の**原因取り**。
       消え方の候補は ①孤児ドラッグの kf-drag / kf-out（不透明度 .35 / .15）②display:none（削除の楽観表示）③left が箱の外。
       描き直し直後と 0.5 s ごとに全アイコンを見回り、掴んでいる 1 枚以外にこれらが残っていれば**直して**、何を直したかを
       右の箱の下段（kf-dbg）と console に残す。実機で dbg の文字が出たら、その中身が原因。原因が分かったら外す */
  var pendingDel = {};
  function dbg(msg) {
    var v = document.querySelector('#kf-preview .kf-prev-video');
    var st = 'rev=' + curRev() + ' q=' + sendQ.length + (inflight ? ' inflight' : '') + (drag ? ' drag#' + drag.i : '')
           + (v && !v.hidden ? ' video(rs=' + v.readyState + (v.paused ? ',paused' : ',playing') + ')' : '');
    var line = msg + ' [' + st + ']';
    try { console.warn('[kf-dbg] ' + line); } catch (err) {}
    var el = document.querySelector('#kf-summary .kf-sum');
    if (el) {
      var d = el.parentNode.querySelector('.kf-dbg');
      if (!d) { d = document.createElement('div'); d.className = 'kf-dbg'; el.parentNode.appendChild(d); }
      if (d.textContent !== 'dbg: ' + line) { d.textContent = 'dbg: ' + line; }   // 同じ文字は書かない（観測ループ防止）
    }
  }
  function healIcons(why) {
    var t = track(); if (!t) { return; }
    var ics = t.querySelectorAll('.kf-ic'); var fixed = [];
    for (var k = 0; k < ics.length; k++) {
      var ic = ics[k];
      if ((drag && ic === drag.ic) || ic.classList.contains('kf-loading')) { continue; }
      var i = ic.dataset.i, bad = [];
      if (ic.classList.contains('kf-drag')) { ic.classList.remove('kf-drag'); bad.push('drag'); }
      if (ic.classList.contains('kf-out')) { ic.classList.remove('kf-out'); bad.push('out'); }
      if (ic.style.display === 'none' && !pendingDel[i]) { ic.style.display = ''; bad.push('hidden'); }
      if (!bad.length) {
        var cs = getComputedStyle(ic);
        if (parseFloat(cs.opacity) < 0.3) { ic.style.opacity = '1'; bad.push('op=' + cs.opacity); }
        if (cs.display === 'none' && !pendingDel[i]) { bad.push('css-none'); }
        var r = ic.getBoundingClientRect(), tb = t.getBoundingClientRect();
        if (r.width && (r.right < tb.left || r.left > tb.right)) { ic.style.left = leftCss(parseFloat(ic.dataset.pos || '0') || 0); bad.push('left=' + ic.style.left); }
        var img = ic.querySelector('img'); if (img && img.complete && img.naturalWidth === 0) { bad.push('img-broken'); }
      }
      if (bad.length) { fixed.push('#' + i + ':' + bad.join('+')); }
    }
    if (fixed.length) { dbg(why + ' ' + fixed.join(' ')); }
  }
  setInterval(function () { healIcons('tick'); }, 500);
  function track() { return document.querySelector('#kf-list .kf-tl-track'); }
  function tl() { return document.querySelector('#kf-list .kf-tl'); }
  function clamp01(v) { return Math.max(0, Math.min(1, v)); }
  var IC = 56;   // アイコンの一辺（px）。Python の KF_ICON_PX / CSS と揃える
  function posOf(clientX) {
    // アイコンは箱の内側に収める写像: 中心が [left+IC/2, right-IC/2] を動く
    var t = track(); if (!t) { return 0; }
    var b = t.getBoundingClientRect();
    return clamp01((clientX - (b.left + IC / 2)) / Math.max(1, b.width - IC));
  }
  function leftCss(pos) { return 'calc(' + (IC / 2) + 'px + ' + (pos * 100).toFixed(2) + '% - ' + (pos * IC).toFixed(1) + 'px)'; }

  /* ── アイコンのドラッグ / 選択 / 外へ出して削除 ── */
  var drag = null;   // {ic, i, x0, y0, moved, out}
  /* ── 空いている場所をドラッグ → プレビュー動画の再生位置（2026-09-15 利用者指示）。
        停止中は停止のまま（その位置のコマが出る）、再生中は再生を保つ（currentTime を変えても再生は続く） ── */
  var scrub = null;
  function prevVideo() { var v = document.querySelector('#kf-preview .kf-prev-video'); return (v && !v.hidden && v.getAttribute('src')) ? v : null; }
  function seekTo(pos) {
    var v = prevVideo(); if (!v || !isFinite(v.duration) || v.duration <= 0) { return; }
    try { v.currentTime = Math.max(0, Math.min(v.duration - 0.001, pos * v.duration)); } catch (err) {}
    placePlayhead(pos);
  }
  function placePlayhead(pos) {                 // 再生位置の縦線（Python の描き直しで消えるので都度作る）
    var t = track(); if (!t) { return; }
    var ph = t.querySelector('.kf-playhead');
    if (!ph) { ph = document.createElement('div'); ph.className = 'kf-playhead'; t.appendChild(ph); }
    ph.style.left = 'calc(' + IC + 'px + ' + (pos * 100).toFixed(2) + '% - ' + (pos * IC).toFixed(1) + 'px)';
  }
  // 縦線の追従。🔴 timeupdate は 4Hz 程度しか来ずカクつく（2026-09-15 利用者指摘）→ 再生中は requestAnimationFrame で毎フレーム動かす。
  //    timeupdate は停止中のシーク（動画側の操作）を拾うためだけに残す
  var phRaf = 0;
  function phTick() {
    phRaf = 0;
    var v = prevVideo(); if (!v || v.paused || v.ended) { return; }
    if (!scrub && isFinite(v.duration) && v.duration > 0) { placePlayhead(v.currentTime / v.duration); }
    phRaf = requestAnimationFrame(phTick);
  }
  function phStart() { if (!phRaf) { phRaf = requestAnimationFrame(phTick); } }
  document.addEventListener('play', function (e) {
    var v = e.target; if (v && v.matches && v.matches('#kf-preview .kf-prev-video')) { phStart(); }
  }, true);
  document.addEventListener('timeupdate', function (e) {
    var v = e.target; if (!v || !v.matches || !v.matches('#kf-preview .kf-prev-video') || scrub) { return; }
    if (!v.paused) { phStart(); return; }                    // 再生中は rAF に任せる（描き直し直後の取りこぼし保険）
    if (isFinite(v.duration) && v.duration > 0) { placePlayhead(v.currentTime / v.duration); }
  }, true);
  document.addEventListener('pointerdown', function (e) {
    var ic = e.target && e.target.closest ? e.target.closest('#kf-list .kf-ic') : null;
    if (!ic && e.button === 0 && e.target && e.target.closest && e.target.closest('#kf-list .kf-tl-track') && prevVideo()) {
      e.preventDefault();
      scrub = {t: e.target.closest('#kf-list .kf-tl-track')};
      try { scrub.t.setPointerCapture(e.pointerId); } catch (err) {}
      seekTo(posOf(e.clientX));
      return;
    }
    if (!ic || e.button !== 0) { return; }
    e.preventDefault();
    if (drag) { endDrag(e); }                    // 🔴 前のドラッグの pointerup が届かなかった（iframe の外で離した等）→ ここで畳む
    drag = {ic: ic, i: parseInt(ic.dataset.i, 10), x0: e.clientX, y0: e.clientY, moved: false, out: false, pid: e.pointerId};
    try { ic.setPointerCapture(e.pointerId); } catch (err) {}
  }, true);
  /* 🔴 2026-09-16 ドラッグ中に Python が描き直すと、掴んでいた要素は DOM から外れる（掴んだまま動かなくなり、
       離すまで古い位置に見える＝「位置が飛ぶ」）。描き直しのたびに同じ data-i の新しい要素へ掴み直す。消えていたら中止 */
  function rebindDrag() {
    if (!drag || document.contains(drag.ic)) { return; }
    var nic = document.querySelector('#kf-list .kf-ic[data-i="' + drag.i + '"]');
    if (!nic) {                                  // 削除された等 → ドラッグを中止
      if (drag.ghost && drag.ghost.parentNode) { drag.ghost.parentNode.removeChild(drag.ghost); }
      drag = null; hidePop(); return;
    }
    drag.ic = nic;
    if (drag.moved) {
      nic.classList.add('kf-drag'); nic.classList.toggle('kf-out', !!drag.out);
      if (typeof drag.pos === 'number') {
        nic.style.left = leftCss(drag.pos);
        var root = tl(); var dur = root ? (parseFloat(root.dataset.dur || '5') || 5) : 5;
        var lab = nic.querySelector('.kf-ic-t'); var txt = (drag.pos * dur).toFixed(1) + 's';
        if (lab && lab.textContent !== txt) { lab.textContent = txt; }   // 同じ値の書き込みは childList 変化になりループする
      }
    }
    if (pop) { popFor = nic; pop.dataset.i = nic.dataset.i; }
    try { nic.setPointerCapture(drag.pid); } catch (err) {}
  }
  function makeGhost(ic) {
    var g = document.createElement('div'); g.className = 'kf-ghost';
    var img = ic.querySelector('img');
    if (img) { var im = document.createElement('img'); im.src = img.getAttribute('src'); im.draggable = false; g.appendChild(im); }
    document.body.appendChild(g);
    return g;
  }
  document.addEventListener('pointermove', function (e) {
    if (scrub) { seekTo(posOf(e.clientX)); return; }
    if (!drag) { return; }
    var dx = e.clientX - drag.x0, dy = e.clientY - drag.y0;
    if (!drag.moved && Math.hypot(dx, dy) < 3) { return; }
    if (!drag.moved) {
      drag.moved = true;
      // 🆕 吹き出しは消さず、半透明で分身に付いてくる（2026-09-15 利用者指示）。出ていなければ出す
      if (!pop || popFor !== drag.ic) { showPop(drag.ic); }
      if (pop) { pop.classList.add('kf-pop-drag'); }
      drag.ic.classList.add('kf-drag');          // 元のアイコンは半透明で track に残る（位置の目安）
      drag.ghost = makeGhost(drag.ic);           // 分身が指に付いてくる（track の外でも見える）
    }
    var t = track(); var root = tl(); if (!t || !root) { return; }
    var b = t.getBoundingClientRect();
    var pos = posOf(e.clientX);
    drag.ic.style.left = leftCss(pos);
    var dur = parseFloat(root.dataset.dur || '5') || 5;
    var lab = drag.ic.querySelector('.kf-ic-t');
    if (lab) { lab.textContent = (pos * dur).toFixed(1) + 's'; }
    if (drag.ghost) {
      drag.ghost.style.left = (e.clientX - IC / 2) + 'px';
      drag.ghost.style.top = (e.clientY - IC / 2) + 'px';
    }
    if (pop && popFor === drag.ic) {             // 吹き出しは分身の真上に。時刻・比率も追従
      var pw = pop.offsetWidth || 400, ph = pop.offsetHeight || 160;
      var gl = Math.max(8, Math.min(window.innerWidth - pw - 8, e.clientX - pw / 2));
      var gt = e.clientY - IC / 2 - ph - 10;
      if (gt < 8) { gt = Math.min(window.innerHeight - ph - 8, e.clientY + IC / 2 + 10); }
      pop.style.left = gl + 'px'; pop.style.top = gt + 'px';
      var pm = pop.querySelector('.kf-pop-meta');
      if (pm) { pm.textContent = (pos * dur).toFixed(2) + ' s ・ ' + Math.round(pos * 100) + ' %'; }
    }
    // 上下に track の外へ出たら「離すと削除」: 分身に × を重ねる
    var out = (e.clientY < b.top) || (e.clientY > b.bottom);
    if (out !== drag.out) {
      drag.out = out;
      if (drag.ghost) { drag.ghost.classList.toggle('kf-out', out); }
      drag.ic.classList.toggle('kf-out', out);
    }
    drag.pos = pos;
  }, true);
  function endDrag(e) {
    if (scrub) { scrub = null; return; }
    if (!drag) { return; }
    var d = drag; drag = null;
    d.ic.classList.remove('kf-drag'); d.ic.classList.remove('kf-out');
    if (d.ghost && d.ghost.parentNode) { d.ghost.parentNode.removeChild(d.ghost); }
    hidePop();                                   // Python が描き直すので一度閉じる（ホバーし直せばまた出る）
    // 🆕 楽観的に反映（2026-09-15 利用者指示「ドラッグしたらすぐ反映」）: 離した位置に置いたまま選択状態にし、
    //    Python の描き直し（data-rev）で正式な絵に置き換わる。pos は却下されないので戻す必要は無い。削除は即座に隠す
    var sib = document.querySelectorAll('#kf-list .kf-ic');
    for (var k = 0; k < sib.length; k++) { sib[k].classList.toggle('kf-sel', sib[k] === d.ic); }
    if (!d.moved) { send({op: 'sel', i: d.i}); return; }
    if (d.out) { d.ic.style.display = 'none'; send({op: 'del', i: d.i}); return; }
    send({op: 'pos', i: d.i, pos: typeof d.pos === 'number' ? d.pos : posOf(e.clientX)});
  }
  document.addEventListener('pointerup', endDrag, true);
  document.addEventListener('pointercancel', endDrag, true);

  /* ── アイコンにホバーで吹き出し（名前 / 時刻 / 全画面 / 削除）。吹き出しへマウスを移しても消えない ── */
  var pop = null, popTimer = null, popFor = null;
  function hidePop() { if (pop && pop.parentNode) { pop.parentNode.removeChild(pop); } popFor = null; }
  function schedHide() { clearTimeout(popTimer); if (drag && pop && popFor === drag.ic) { return; } popTimer = setTimeout(hidePop, 220); }   // ドラッグ中は消さない
  function showPop(ic) {
    clearTimeout(popTimer);
    var root = tl(); var t = track(); if (!root || !t || !ic) { return; }
    if (pop && popFor === ic) { return; }
    hidePop();
    pop = document.createElement('div'); pop.className = 'kf-pop'; popFor = ic;
    pop.dataset.i = ic.dataset.i; pop.dataset.prev = ic.dataset.prev || '';
    var img = ic.querySelector('img');
    // 枚ごとの効き目: 「全体に従う」チェック ＋ スライダー。未指定（data-str 空）は全体の値を表示
    var smin = parseFloat(root.dataset.smin || '0.3') || 0.3;
    var gEl = document.querySelector('#kf-strength input[type="range"]');
    var gval = gEl ? parseFloat(gEl.value) : 1.0;
    var own = ic.dataset.str ? parseFloat(ic.dataset.str) : NaN;
    var follow = isNaN(own);
    var cur = follow ? gval : own;
    // 🆕 2026-09-15（利用者指示）: 2 段組み。上段 = サムネ / 名前・時刻 / ⛶ ×、下段 = Strength（見出し＋「全体に従う」、その下にスライダー）。
    //    スライダーは disabled にしない（disabled だと触れない）。全体に従う間は薄く見せ、**触ったら自動で「全体に従う」が外れる**
    pop.innerHTML = '<div class="kf-pop-top">' + (img ? '<img src="' + img.getAttribute('src') + '">' : '')
      + '<div class="kf-pop-body"><div class="kf-pop-name"></div><div class="kf-pop-meta"></div><div class="kf-pop-meta2"></div></div>'
      + '<div class="kf-pop-btns"><button class="kf-full" type="button" title="full screen">⛶</button>'
      + '<button class="kf-del" type="button" title="delete">✕</button></div></div>'
      + '<div class="kf-pop-str' + (follow ? ' kf-following' : '') + '"><div class="kf-pop-str-h"><span class="kf-pop-str-t">Strength</span>'
      + '<label><input type="checkbox" class="kf-follow"' + (follow ? ' checked' : '') + '> <span class="kf-follow-t"></span></label></div>'
      + '<div class="kf-pop-str-r"><span class="kf-str-min">' + smin.toFixed(1) + '</span>'
      + '<input type="range" class="kf-str" min="' + smin + '" max="1" step="0.05" value="' + cur.toFixed(2) + '">'
      + '<span class="kf-str-v">' + cur.toFixed(2) + '</span></div></div>';
    pop.querySelector('.kf-pop-name').textContent = ic.dataset.name || '';
    pop.querySelector('.kf-pop-meta').textContent = (ic.dataset.sec || '') + ' s ・ ' + (ic.dataset.pct || '') + ' %';
    pop.querySelector('.kf-pop-meta2').textContent = ic.dataset.n || '';
    pop.querySelector('.kf-follow-t').textContent = root.dataset.follow || 'follow';
    var box = pop.querySelector('.kf-pop-str');
    var rng = pop.querySelector('.kf-str'); var rv = pop.querySelector('.kf-str-v'); var fc = pop.querySelector('.kf-follow');
    function unfollow() { if (fc.checked) { fc.checked = false; } box.classList.remove('kf-following'); }
    rng.addEventListener('pointerdown', unfollow);
    rng.addEventListener('input', function () { unfollow(); rv.textContent = parseFloat(rng.value).toFixed(2); });
    rng.addEventListener('change', function () {
      unfollow();
      var v = parseFloat(rng.value); ic.dataset.str = String(v);
      send({op: 'str', i: parseInt(ic.dataset.i, 10), v: v});
    });
    fc.addEventListener('change', function () {
      if (fc.checked) { box.classList.add('kf-following'); rng.value = gval.toFixed(2); rv.textContent = gval.toFixed(2); ic.dataset.str = '';
                        send({op: 'str', i: parseInt(ic.dataset.i, 10), v: null}); }
      else { box.classList.remove('kf-following'); }
    });
    document.body.appendChild(pop);
    // 🔴 動画側（上）に出す（利用者指定）。上に収まらなければ下へ。画面の端では内側へ寄せる
    var ib = ic.getBoundingClientRect(); var pw = pop.offsetWidth || 360; var ph = pop.offsetHeight || 110;
    var left = Math.max(8, Math.min(window.innerWidth - pw - 8, ib.left + ib.width / 2 - pw / 2));
    var top = ib.top - ph - 10;
    if (top < 8) { top = Math.min(window.innerHeight - ph - 8, ib.bottom + 10); }
    pop.style.left = left + 'px'; pop.style.top = top + 'px';
    pop.addEventListener('pointerenter', function () { clearTimeout(popTimer); });
    pop.addEventListener('pointerleave', schedHide);
  }
  document.addEventListener('pointerover', function (e) {
    var ic = e.target && e.target.closest ? e.target.closest('#kf-list .kf-ic') : null;
    if (ic && !drag) { showPop(ic); }
  }, true);
  window.addEventListener('scroll', function () { if (pop) { hidePop(); } }, true);
  document.addEventListener('pointerout', function (e) {
    var ic = e.target && e.target.closest ? e.target.closest('#kf-list .kf-ic') : null;
    if (!ic) { return; }
    var r = e.relatedTarget;
    if (r && r.closest && (r.closest('.kf-pop') || r.closest('#kf-list .kf-ic') === ic)) { return; }
    schedHide();
  }, true);

  /* ── 吹き出しのボタン（全画面 / 削除） ── */
  document.addEventListener('click', function (e) {
    var t = e.target; if (!t || !t.closest) { return; }
    var del = t.closest('.kf-pop .kf-del');
    if (del) {
      e.preventDefault(); var pp = del.closest('.kf-pop'); var di = parseInt(pp.dataset.i, 10);
      var dic = document.querySelector('#kf-list .kf-ic[data-i="' + di + '"]'); if (dic) { dic.style.display = 'none'; }
      hidePop(); send({op: 'del', i: di}); return;
    }
    var full = t.closest('.kf-pop .kf-full');
    if (full) {
      e.preventDefault();
      var info = full.closest('.kf-pop');
      var src = info && info.dataset.prev;
      if (!src) { return; }
      var ov = document.createElement('div'); ov.className = 'kf-fs';
      var im = document.createElement('img'); im.src = src; ov.appendChild(im);
      ov.addEventListener('click', function () { ov.remove(); });
      document.body.appendChild(ov);
      return;
    }
    var fs = t.closest('.kf-fs'); if (fs) { fs.remove(); }
  }, true);
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { var fs = document.querySelector('.kf-fs'); if (fs) { fs.remove(); } }
  });

  /* ── track へ画像ファイルをドロップ → その位置へ読み込み ── */
  var dropLine = null;
  function showDropLine(x) {
    var t = track(); if (!t) { return; }
    if (!dropLine) { dropLine = document.createElement('div'); dropLine.className = 'kf-drop-line'; }
    if (dropLine.parentNode !== t) { t.appendChild(dropLine); }
    dropLine.style.left = leftCss(posOf(x));
  }
  function hideDrop() {
    var root = tl(); if (root) { root.classList.remove('kf-arm-drop'); }
    if (dropLine && dropLine.parentNode) { dropLine.parentNode.removeChild(dropLine); }
  }
  function hasFiles(e) {
    var dt = e.dataTransfer; if (!dt) { return false; }
    if (dt.types) { for (var i = 0; i < dt.types.length; i++) { if (dt.types[i] === 'Files') { return true; } } }
    return !!(dt.files && dt.files.length);
  }
  document.addEventListener('dragover', function (e) {
    var t = e.target && e.target.closest ? e.target.closest('#kf-list .kf-tl-track') : null;
    if (!t || !hasFiles(e)) { return; }
    e.preventDefault(); e.stopPropagation();
    try { e.dataTransfer.dropEffect = 'copy'; } catch (err) {}
    var root = tl(); if (root) { root.classList.add('kf-arm-drop'); }
    showDropLine(e.clientX);
  }, true);
  document.addEventListener('dragleave', function (e) {
    var t = e.target && e.target.closest ? e.target.closest('#kf-list .kf-tl-track') : null;
    if (!t) { return; }
    // 子要素間の移動でも dragleave は飛ぶ。本当に外へ出たときだけ消す
    var r = e.relatedTarget; if (r && r.closest && r.closest('#kf-list .kf-tl-track')) { return; }
    hideDrop();
  }, true);
  document.addEventListener('drop', function (e) {
    var t = e.target && e.target.closest ? e.target.closest('#kf-list .kf-tl-track') : null;
    if (!t || !hasFiles(e)) { hideDrop(); return; }
    e.preventDefault(); e.stopPropagation();       // Gradio のファイルドロップ処理に渡さない
    var pos = posOf(e.clientX);
    hideDrop();
    var files = Array.prototype.slice.call(e.dataTransfer.files || []).filter(function (f) {
      return !f.type || f.type.indexOf('image/') === 0;
    });
    if (!files.length) { return; }
    // 読み込み中の仮アイコン（Python がタイムラインを描き直すと一緒に消える。届かなかったときの保険で 20 秒後に消す）
    (function () {
      var t2 = track(); var root = tl(); if (!t2) { return; }
      var txt = (root && root.dataset.loading) || 'Loading…';
      var emp = t2.querySelector('.kf-tl-empty'); if (emp) { emp.style.display = 'none'; }
      files.forEach(function (_f, k) {
        var ph = document.createElement('div'); ph.className = 'kf-ic kf-loading';
        ph.style.left = leftCss(Math.min(1, pos + k * 0.05));
        ph.innerHTML = '<span class="kf-ph"><i class="kf-spin"></i></span><span class="kf-ic-t">' + txt + '</span>';
        t2.appendChild(ph);
        setTimeout(function () { if (ph.parentNode) { ph.parentNode.removeChild(ph); } }, 20000);
      });
    })();
    var out = []; var left = files.length;
    files.forEach(function (f, k) {
      var rd = new FileReader();
      rd.onload = function () { out[k] = {name: f.name, data: rd.result}; if (--left === 0) { send({op: 'drop', pos: pos, files: out}); } };
      rd.onerror = function () { if (--left === 0) { send({op: 'drop', pos: pos, files: out.filter(Boolean)}); } };
      rd.readAsDataURL(f);
    });
  }, true);

  /* ── PREVIEW の中身を 16:9 の箱へ写す ── */
  function mainMedia() {
    var v = document.querySelector('#preview-video video');
    if (v && v.currentSrc) { return {kind: 'video', src: v.currentSrc}; }
    if (v && v.src) { return {kind: 'video', src: v.src}; }
    var im = document.querySelector('#preview-img img');
    if (im && im.src) { return {kind: 'img', src: im.src}; }
    return null;
  }
  var lastSrc = null;
  function syncSummary() {                      // 右の箱の下段（枚数・秒数）。kf_render の data-summary を写す
    var root = tl(); var el = document.querySelector('#kf-summary .kf-sum');
    if (root && el && el.textContent !== (root.dataset.summary || '')) { el.textContent = root.dataset.summary || ''; }
  }
  function syncPreview() {
    syncSummary();
    var box = document.querySelector('#kf-preview .kf-prevbox'); if (!box) { return; }
    // 🔴 <video> は Gradio が描き直す HTML の**外**（#kf-preview 直下）に 1 度だけ作り、箱の上に重ねる。
    //    HTML の中に置くと選択のたびに作り直されて読み直し・再生位置リセットになる（2026-09-15）
    var host = document.querySelector('#kf-preview');
    var vid = host ? host.querySelector(':scope > video.kf-prev-video') : null;
    if (host && !vid) {
      vid = document.createElement('video'); vid.className = 'kf-prev-video';
      vid.muted = true; vid.loop = true; vid.playsInline = true; vid.controls = true; vid.hidden = true;
      host.appendChild(vid);
    }
    var still = box.querySelector('.kf-prev-still, .kf-prev-none');
    var m = mainMedia();
    if (m && m.kind === 'video') {
      if (vid) {
        if (vid.getAttribute('src') !== m.src) { vid.setAttribute('src', m.src); vid.load(); }
        vid.hidden = false;
      }
      if (still) { still.style.visibility = 'hidden'; }
    } else if (m && m.kind === 'img') {
      if (vid) { vid.hidden = true; }
      if (still && still.tagName === 'IMG' && !still.dataset.kf) { /* 選択中の静止画を優先 */ }
    } else {
      if (vid) { vid.hidden = true; }
      if (still) { still.style.visibility = ''; }
    }
    lastSrc = m ? m.src : null;
  }
  var mo = new MutationObserver(function () { onRerender(); window.requestAnimationFrame(syncPreview); });
  mo.observe(document.body, {subtree: true, childList: true, attributes: true, attributeFilter: ['src', 'data-rev']});
  setInterval(syncPreview, 1500);
  syncPreview();
}
