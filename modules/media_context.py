# Copyright (C) 2026 CALMDUST / AiHUB
# SPDX-License-Identifier: Apache-2.0
"""media_context — 既存の動画の任意の時刻 t から「撮り直す／延長する」（Media Context と Retake）。MiniMax H3 WebUI の拡張モジュール

設計は WebUI のプロジェクトの retake_design_memo.md（2026-09-17）:
  ・**Motion Context**（本体の長尺）は前セグメントの末尾 22 コマ（＋その区間の音声）を次のクリップの文脈にする。
  ・**Media Context** はそれを既存のメディア（生成物でも実写でも）の任意の時刻 t に広げたもの:
      映像 … t の直前 22 コマを読み出して文脈にする（本体が再エンコードする＝潜在の控えは要らない）
      音声 … t の前後の波形を音声 VAE でエンコードし、直前 22 コマぶん（約 37 潜在）を文脈にする
  ・**Retake** … その文脈で新しいクリップを作り、[0, t) の元の映像の後ろにつなぐ。t＝終わりなら「延長」。
      新しいクリップの先頭 22 コマは文脈の描き直しなので、元の 22 コマと滑らかに混ぜてつなぐ（本体の長尺の blend と同じ考え方）。
      結果は 2 本: つないだもの（_retake.mp4）と新しい部分だけ（_retake_seg.mp4）。元のファイルは触らない。

0.1.0 はエンジンだけ（UI はまだ）。本体からは module_service("media_context_retake") で呼ぶ。計測セル 180 で実機確認する。
0.2.0: 計測セル 180 の利用者所見（2026-10-24）: 音声の文脈ありは音が自然につながるが、元の 5 秒のプロンプトのままなので
       **最初のセリフをもう一度しゃべる**（新しいクリップを「0 秒から始まる動画」として作るため）。文脈なしは音が壊れる → 音声の文脈は常に使う。
       → **原点シフト**（設計メモ 4.2）を試せるようにした: 新しいクリップの映像・音声の時刻（RoPE の時間）に「文脈の始まり＝t−22 コマ」の
       秒数を足し、モデルには「元の動画の途中から先」として見せる。元のプロンプトの時刻の指定（0〜2 秒のセリフ等）が「済んだこと」になる見込み。
       学習に無い見せ方（文章のすぐ後に映像が来ない）なので、計測セル 181 で ON/OFF を比べてから既定を決める。
       → セル181: 効いたのは「続きのプロンプト」。原点シフト単独では言い直しが残る＝既定 OFF（オプションとして残す）。
0.3.0: 利用者要望（2026-10-24）「元のプロンプトが動画に入っているなら、人物やロケーションは自動で維持して、書いた挙動だけ変わる仕組み」。
       inherit=True で元の動画のメタから引き継ぐ:
         ・モード（R2V など）と RefMod（名前・強さ）… 生成の間だけ本体の RefMod の選択を元のものにする（終わったら戻す）
         ・Turbo LoRA・強さ・Steps … セル182: 元と同じにすると「とても自然に追加生成できる」（利用者）
         ・プロンプト … 書いたのが「挙動だけ」（節の見出しが無い文）なら compose_prompt で元のプロンプトと合わせる:
           人物の定義・保持の分析・音の節は元のまま、summary は元の場所の文＋「同じ人・同じ場所で直前から続く」、
           detailed_description は元の光・場所の文＋[Shot 1] の構図の文＋書いた挙動＋元のカメラと終わり方の文
0.3.1: セル183 の利用者所見「やや暗めになる。lightx2v の Ref 版はどれもその傾向」。測ると（183 の出力）明るさ（灰色の平均）が
       文脈 60.8 → 新しい部分の前半 54.0・後半 50.1、明るい所（上位 5%）167→144、しかも文脈が終わった直後の 1 コマで 59.8→55.9 と段差。
       → **明るさ合わせ（tone、既定 ON）**: 新しい部分の各コマに、文脈（元の 22 コマ）の明るさ ÷ そのコマの明るさの流れ を掛ける。
         流れは 1 秒（25 コマ）の中央値（段差の位置で前後を混ぜない＝平均だと段差の手前で明るく行き過ぎた）。倍率は 0.8〜1.25、
         RGB に同じ倍率（色味は変えない。character_guide と同じく足し引きではなく掛け算＝黒が浮かない）。
         183 の出力で: 新しい部分 54.0／50.1 → 60.6、t の段差なし、細かい揺れは元と同程度（0.24／元 0.33）
本体の関数（_run_pipe・ensure_mode・_blend_head・_mux_audio など）を借りて動く。単体では動かない。
"""
import datetime
import json
import os
import subprocess
import threading
import time

import numpy as np

NAME = "media_context"
VERSION = "0.3.1"
API = 1
SLOTS = ()

AUDIO_LAT_PER_SEC = 40.0                # 音声 VAE の潜在の速さ（diffusers の MINIMAX_H3_AUDIO_LATENTS_PER_SECOND）
AUDIO_WIN_BEFORE = 4.0                  # 音声の文脈を取るとき、t の何秒前からエンコードするか（端の癖を文脈から遠ざける）
AUDIO_WIN_AFTER = 0.5                   # t の後ろも少し含めてエンコードする（窓の終わりの端の癖を文脈に入れない）
AUDIO_XFADE_MS = 20                     # t で元の音と新しい音をつなぐ短いクロスフェード
POLL_SEC = 0.5
TONE_WIN = 25                           # 0.3.1 明るさの流れを見る幅（コマ。中央値）
TONE_CLIP = (0.8, 1.25)                 # 0.3.1 明るさを合わせる倍率の範囲
ROPE_PER_SEC = 40.0                     # 映像（5/3 × 24fps）と音声（40 潜在/秒）の RoPE の時間は、どちらも 1 秒 = 40

I18N = {
    "🎬 Retake: {v0} の {v1} 秒から {v2} 秒ぶん作ります（文脈 {v3} コマ・音声 {v4}）": {
        "en": "🎬 Retake: making {v2} s from {v1} s of {v0} (context {v3} frames, audio {v4})",
        "zh": "🎬 Retake：从 {v0} 的 {v1} 秒处生成 {v2} 秒（上下文 {v3} 帧・音频 {v4}）",
        "ko": "🎬 Retake: {v0} 의 {v1} 초부터 {v2} 초 분량을 만듭니다(문맥 {v3} 프레임·음성 {v4})"},
    "あり": {"en": "yes", "zh": "有", "ko": "있음"},
    "なし（元の動画に音が無い）": {"en": "none (the source has no audio)", "zh": "无（原视频没有音频）", "ko": "없음(원본 영상에 소리가 없음)"},
    "なし（使わない指定）": {"en": "none (turned off)", "zh": "无（指定不使用）", "ko": "없음(사용하지 않도록 지정)"},
    "   原点シフト: 新しいクリップを元の動画の {v0} 秒から先として作ります": {
        "en": "   Origin shift: the new clip is made as the part of the source from {v0} s on",
        "zh": "   原点平移：把新片段当作原视频 {v0} 秒之后的部分来生成",
        "ko": "   원점 이동: 새 클립을 원본 영상의 {v0} 초 이후 부분으로 만듭니다"},
    "❌ t が早すぎます（文脈に {v0} コマ＝{v1} 秒以上が要ります）": {
        "en": "❌ t is too early (the context needs at least {v0} frames = {v1} s)",
        "zh": "❌ t 太靠前（上下文至少需要 {v0} 帧 = {v1} 秒）",
        "ko": "❌ t 가 너무 이릅니다(문맥에 {v0} 프레임 = {v1} 초 이상이 필요합니다)"},
    "❌ 動画を読めませんでした: {v0}": {"en": "❌ Could not read the video: {v0}", "zh": "❌ 无法读取视频：{v0}", "ko": "❌ 영상을 읽을 수 없습니다: {v0}"},
    "❌ Retake に失敗しました: {v0}": {"en": "❌ Retake failed: {v0}", "zh": "❌ Retake 失败：{v0}", "ko": "❌ Retake 에 실패했습니다: {v0}"},
    "⚠️ 音声の文脈を作れませんでした（映像だけで続けます）: {v0}": {
        "en": "⚠️ Could not build the audio context (continuing with video only): {v0}",
        "zh": "⚠️ 无法生成音频上下文（仅用视频继续）：{v0}",
        "ko": "⚠️ 음성 문맥을 만들 수 없습니다(영상만으로 계속합니다): {v0}"},
    "⏳ Retake 生成中  {v0}/{v1} steps  ⏱ {v2}s": {
        "en": "⏳ Retake generating  {v0}/{v1} steps  ⏱ {v2}s", "zh": "⏳ Retake 生成中  {v0}/{v1} steps  ⏱ {v2}s",
        "ko": "⏳ Retake 생성 중  {v0}/{v1} steps  ⏱ {v2}s"},
    "📼 つないで書き出しています…": {"en": "📼 Joining and writing…", "zh": "📼 正在拼接并导出…", "ko": "📼 이어 붙여 내보내는 중…"},
    "✅ Retake 完了（{v0} 秒）: つないだもの {v1} ／ 新しい部分 {v2}": {
        "en": "✅ Retake done ({v0} s): joined {v1} / new part {v2}",
        "zh": "✅ Retake 完成（{v0} 秒）：拼接版 {v1} ／ 新部分 {v2}",
        "ko": "✅ Retake 완료({v0} 초): 이어 붙인 것 {v1} / 새 부분 {v2}"},
    "⚠️ 元の動画にメタ（プロンプト）が無いので引き継げません。書いたプロンプトのまま作ります": {
        "en": "⚠️ The source has no metadata (prompt), so nothing can be inherited. Using the prompt as written",
        "zh": "⚠️ 原视频没有元数据（提示词），无法继承。按所写的提示词生成",
        "ko": "⚠️ 원본 영상에 메타데이터(프롬프트)가 없어 이어받을 수 없습니다. 쓴 프롬프트 그대로 만듭니다"},
    "🧩 元のプロンプトの人物・場所・構図・音を残し、書いた挙動を入れて続きのプロンプトを組みました": {
        "en": "🧩 Built the continuation prompt: people, place, framing and sound from the original prompt, plus the action you wrote",
        "zh": "🧩 已组合续写提示词：保留原提示词的人物・地点・构图・声音，并加入你写的动作",
        "ko": "🧩 원래 프롬프트의 인물·장소·구도·소리를 남기고, 쓴 동작을 넣어 이어지는 프롬프트를 만들었습니다"},
    "   引き継ぎ: モード {v0} / Turbo {v1} × {v2} / Steps {v3}": {
        "en": "   Inherited: mode {v0} / Turbo {v1} × {v2} / Steps {v3}", "zh": "   继承：模式 {v0} / Turbo {v1} × {v2} / Steps {v3}",
        "ko": "   이어받음: 모드 {v0} / Turbo {v1} × {v2} / Steps {v3}"},
    "   RefMod: {v0}": {"en": "   RefMod: {v0}", "zh": "   RefMod：{v0}", "ko": "   RefMod: {v0}"},
    "⚠️ 見つからない RefMod があります（無しで作ります）: {v0}": {
        "en": "⚠️ Some RefMods were not found (making it without them): {v0}", "zh": "⚠️ 有找不到的 RefMod（不使用它们生成）：{v0}",
        "ko": "⚠️ 찾을 수 없는 RefMod 가 있습니다(없이 만듭니다): {v0}"},
    "   明るさ合わせ: 新しい部分を文脈の明るさに合わせました（×{v0}〜×{v1}）": {
        "en": "   Brightness match: the new part was matched to the context brightness (×{v0}–×{v1})",
        "zh": "   亮度对齐：已将新部分对齐到上下文的亮度（×{v0}〜×{v1}）",
        "ko": "   밝기 맞춤: 새 부분을 문맥의 밝기에 맞췄습니다(×{v0}〜×{v1})"},
    "⚠️ 明るさ合わせに失敗しました（そのまま書き出します）: {v0}": {
        "en": "⚠️ Brightness match failed (writing as is): {v0}", "zh": "⚠️ 亮度对齐失败（按原样导出）：{v0}",
        "ko": "⚠️ 밝기 맞춤에 실패했습니다(그대로 내보냅니다): {v0}"},
    "   文脈の作り方: 映像 {v0}・音声 {v1} 潜在": {
        "en": "   Context: video {v0}, audio {v1} latents", "zh": "   上下文：视频 {v0}・音频 {v1} 个潜变量",
        "ko": "   문맥: 영상 {v0}·음성 {v1} 잠재"},
}

_ST = {"ctx": None}


def _g():
    return _ST["ctx"].g


def _T(s, **kw):
    return _ST["ctx"].T(s, **kw)


# ------------------------------------------------------------------
#  読み出し（映像のコマ・音声の波形）
# ------------------------------------------------------------------
def _read_frames(path, w, h, start, count):
    """start コマ目から count コマを (count,H,W,3) uint8 で（コマ番号で選ぶ＝秒で切るより正確）"""
    ff = _g()["_ffmpeg_exe"]()
    raw = subprocess.run(
        [ff, "-v", "error", "-i", path, "-vf", f"select='between(n\\,{int(start)}\\,{int(start + count - 1)})'",
         "-vsync", "0", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{int(w)}x{int(h)}", "-"],
        capture_output=True, check=True).stdout
    per = int(w) * int(h) * 3
    n = len(raw) // per
    if n < count:
        raise RuntimeError(f"{start} コマ目から {count} コマ読めませんでした（{n} コマ）")
    return np.frombuffer(raw, np.uint8, count=count * per).reshape(count, int(h), int(w), 3).copy()


def _read_audio(path, sr, start=None, dur=None):
    """(samples, 2) float32 at sr。音声が無ければ None"""
    ff = _g()["_ffmpeg_exe"]()
    cmd = [ff, "-v", "error"]
    if start is not None:
        cmd += ["-ss", f"{max(0.0, float(start)):.6f}"]
    cmd += ["-i", path]
    if dur is not None:
        cmd += ["-t", f"{float(dur):.6f}"]
    cmd += ["-vn", "-ac", "2", "-ar", str(int(sr)), "-f", "f32le", "-"]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0 or not r.stdout:
        return None
    return np.frombuffer(r.stdout, np.float32).reshape(-1, 2).copy()


def _audio_sr():
    p = _g().get("pipe")
    try:
        return int(p.audio_vae.config.sampling_rate)
    except Exception:                                             # noqa: BLE001
        return int(getattr(p, "audio_sampling_rate", 32000) or 32000)


def audio_context(path, t, ctx_frames, fps=24.0):
    """t の直前 ctx_frames コマぶんの音声の文脈 → (2, C, m) 正規化済みの潜在（CPU float32）。音が無ければ None

    diffusers の参照音声のエンコード（posterior の mode を latents_mean / latents_std で正規化）と同じ空間。
    本体の mc_arm は (channels, C, M) を受け取り、行に並べ替えて条件列へ入れる。
    窓は [t−4 秒, t＋0.5 秒) をまとめてエンコードし、t の直前の m 潜在だけを取る（窓の端の癖を避ける）"""
    import torch
    g = _g()
    pipe = g["pipe"]
    avae = pipe.audio_vae
    sr = _audio_sr()
    ws = max(0.0, float(t) - AUDIO_WIN_BEFORE)
    a = _read_audio(path, sr, ws, (float(t) - ws) + AUDIO_WIN_AFTER)
    if a is None or a.shape[0] < sr * 0.2:
        return None
    m = int(round(ctx_frames / fps * AUDIO_LAT_PER_SEC))
    p0 = next(avae.parameters())
    wave = torch.from_numpy(np.ascontiguousarray(a.T)).to(p0.device, torch.float32)   # (2, N)
    # 🔴 音声 VAE は fp32。SageAttention が全体の既定になっているので、内側だけ native に（本体セル2 の _attn_backend）
    abk = g.get("_attn_backend")
    with (abk("native") if abk is not None else _null()), torch.no_grad():
        post = avae.encode(wave[:, None], return_dict=False)[0]
        z = post.mode().float()                                   # (2, C, M)
    cfg = avae.config
    mean = torch.tensor(cfg.latents_mean, device=z.device, dtype=z.dtype).view(1, -1, 1)
    std = torch.tensor(cfg.latents_std, device=z.device, dtype=z.dtype).view(1, -1, 1)
    z = ((z - mean) / std).cpu()
    end = int(round((float(t) - ws) * z.shape[-1] / (a.shape[0] / sr)))   # t の位置（潜在の番号）
    end = max(m, min(int(z.shape[-1]), end))
    return z[..., end - m:end].contiguous()


class origin_shift:
    """with origin_shift(秒): 生成 1 回ぶん、文章より後ろの行（条件の映像・音声、生成する音声・映像）の RoPE の時間に 秒×40 を足す。
    本体セル2 の `_LayoutStep.build_packed_sequence`（Motion Context の差し替え）を包む。本体セル3 の install_vsa_geo は
    生成のたびに「いまの実体」から包み直すので、functools.wraps で元の署名を見せておく（列の内訳の控えがそのまま動く）"""

    def __init__(self, sec):
        self.sec = float(sec or 0.0)
        self.ls = None
        self.cur = None

    def __enter__(self):
        import functools
        if self.sec <= 0:
            return self
        g = _g()
        self.ls = g.get("_LayoutStep")
        if self.ls is None:
            return self
        self.cur = self.ls.build_packed_sequence
        raw = getattr(self.cur, "_h3_geo_raw", self.cur)
        off = self.sec * ROPE_PER_SEC

        @functools.wraps(raw)
        def shifted(*a, **kw):
            out = raw(*a, **kw)
            tags = kw.get("text_token_tags", a[0] if a else None)
            nt = int(tags.shape[0])
            out[0][nt:, 0] += off
            return out
        self.ls.build_packed_sequence = staticmethod(shifted)
        return self

    def __exit__(self, *a):
        if self.ls is not None and self.cur is not None:
            self.ls.build_packed_sequence = staticmethod(getattr(self.cur, "__func__", self.cur))
        return False


class _null:
    def __enter__(self):
        return None

    def __exit__(self, *a):
        return False


# ------------------------------------------------------------------
#  Retake 本体
# ------------------------------------------------------------------
def _retake_core(src, t, add_sec, prompt, seed, mode=None, refs_by_kind=None, steps=None, use_audio=True, extend=False,
                 shift=False, out_dir=None, tone=True):
    """src の t 秒から add_sec 秒を作り直す（extend=True なら t は動画の終わり）。
    (status, None) を逐次 yield し、最後に (status, {"joined": パス, "seg": パス, ...}) を返す
    out_dir … 0.2.1 書き出し先のフォルダ（計測セルは /content/tNNN/ を渡す。そのときは Drive へ写さない）。None なら /content（LIBRARY に出る）"""
    import torch
    from PIL import Image
    g = _g()
    T = _T
    fps = float(g.get("FPS", 24))
    ctx_n = int(g.get("MOTION_CTX_FRAMES", 22))
    try:
        w, h, n_src, fps_src, has_audio = g["_probe_video"](src)
        if w <= 0 or h <= 0 or n_src <= 0:
            raise RuntimeError("probe")
    except Exception as e:                                        # noqa: BLE001
        yield (T("❌ 動画を読めませんでした: {v0}", v0=f"{e}"), None)
        return
    ti = int(n_src) if extend else int(round(float(t) * fps))
    ti = max(0, min(int(n_src), ti))
    if ti < ctx_n:
        yield (T("❌ t が早すぎます（文脈に {v0} コマ＝{v1} 秒以上が要ります）", v0=ctx_n, v1=f"{ctx_n / fps:.2f}"), None)
        return
    t_cut = ti / fps
    nf = int(g["calc_frames"](float(add_sec) + ctx_n / fps))      # 文脈 22 コマ＋新しい部分（17n+5）
    refs_by_kind = refs_by_kind or {k: [] for k in g["REF_KINDS"]}
    mode = mode or "T2V"
    is_ref = bool(g["is_ref_mode"](mode))
    seg_mode = mode if is_ref else g["I2V_MODE"]                  # 本体の長尺と同じ（文脈のある回は I2V の経路、参照モードはそのまま）
    steps = int(steps or g["_UI_STATE"].get("steps", 4) or 4)
    lines = []
    try:
        ctx_px = _read_frames(src, w, h, ti - ctx_n, ctx_n)
    except Exception as e:                                        # noqa: BLE001
        yield (T("❌ 動画を読めませんでした: {v0}", v0=f"{e}"), None)
        return
    aud = None
    aud_note = T("なし（元の動画に音が無い）") if not has_audio else T("なし（使わない指定）")
    if use_audio and has_audio and g.get("MC_AUDIO", False):
        try:
            aud = audio_context(src, t_cut, ctx_n, fps)
            if aud is not None:
                aud_note = T("あり")
        except Exception as e:                                    # noqa: BLE001
            lines.append(T("⚠️ 音声の文脈を作れませんでした（映像だけで続けます）: {v0}", v0=f"{type(e).__name__}: {e}"))
            aud = None
    lines.insert(0, T("🎬 Retake: {v0} の {v1} 秒から {v2} 秒ぶん作ります（文脈 {v3} コマ・音声 {v4}）",
                      v0=os.path.basename(src), v1=f"{t_cut:.2f}", v2=f"{(nf - ctx_n) / fps:.2f}", v3=ctx_n, v4=aud_note))
    shift_sec = (ti - ctx_n) / fps if shift else 0.0
    if shift_sec > 0:
        lines.append(T("   原点シフト: 新しいクリップを元の動画の {v0} 秒から先として作ります", v0=f"{shift_sec:.2f}"))
    yield ("\n".join(lines), None)

    ok, msg = g["ensure_mode"](seg_mode)
    if not ok:
        yield ("\n".join(lines + [msg]), None)
        return
    mcl = g.get("_MCL")
    if isinstance(mcl, dict):
        mcl.update(want=False, z=None, use=None)                  # 🔴 長尺の潜在の控えを持ち込まない（再エンコードで作る）
    ar = g.get("_AR")
    if isinstance(ar, dict):
        ar["want"] = False
    prog = {"n": 0, "total": steps, "phase": "denoise"}
    box = {}

    def _worker():
        try:
            with origin_shift(shift_sec):
                box["res"] = g["_run_pipe"](seg_mode, prompt, w, h, nf, steps, int(seed), ctx_px[-1], None,
                                            refs_by_kind, prog, mc_frames=ctx_px, mc_audio=aud)
        except BaseException as e:                                # noqa: BLE001
            box["err"] = e

    th = threading.Thread(target=_worker, daemon=True)
    t0 = time.time()
    th.start()
    while th.is_alive():
        yield ("\n".join(lines + [T("⏳ Retake 生成中  {v0}/{v1} steps  ⏱ {v2}s", v0=prog.get("n", 0),
                                    v1=prog.get("total", steps), v2=f"{time.time() - t0:.0f}")]), None)
        time.sleep(POLL_SEC)
    th.join()
    if "err" in box:
        e = box["err"]
        try:
            g["_free_vram"]()
        except Exception:                                         # noqa: BLE001
            pass
        yield ("\n".join(lines + [T("❌ Retake に失敗しました: {v0}", v0=f"{type(e).__name__}: {e}")]), None)
        return
    r = box["res"]
    try:
        src_note = g["mc_ctx_source"]() if "mc_ctx_source" in g else ""
    except Exception:                                             # noqa: BLE001
        src_note = ""
    lines.append(T("   文脈の作り方: 映像 {v0}・音声 {v1} 潜在", v0=src_note or "?", v1=int(aud.shape[-1]) if aud is not None else 0))
    yield ("\n".join(lines + [T("📼 つないで書き出しています…")]), None)

    frames = [f if isinstance(f, Image.Image) else Image.fromarray(np.asarray(f)) for f in r["frames"]]
    frames = [f.convert("RGB") if f.size == (w, h) else f.convert("RGB").resize((w, h), Image.Resampling.LANCZOS)
              for f in frames]
    if tone and len(frames) > ctx_n:
        try:
            fixed, (g0, g1) = tone_match(frames[ctx_n:], ctx_px)
            frames = frames[:ctx_n] + fixed
            if abs(g0 - 1.0) >= 0.01 or abs(g1 - 1.0) >= 0.01:
                lines.append(T("   明るさ合わせ: 新しい部分を文脈の明るさに合わせました（×{v0}〜×{v1}）", v0=f"{g0:.2f}", v1=f"{g1:.2f}"))
        except Exception as e:                                    # noqa: BLE001
            lines.append(T("⚠️ 明るさ合わせに失敗しました（そのまま書き出します）: {v0}", v0=f"{e}"))
    joined_head = g["_blend_head"](frames, ctx_px, ctx_n)         # 先頭 22 コマ（文脈の描き直し）を元の 22 コマへ滑らかに
    stamp = datetime.datetime.now().strftime("%H%M%S")
    od = str(out_dir) if out_dir else "/content"
    os.makedirs(od, exist_ok=True)
    base = os.path.join(od, f"minimax_h3_retake_{stamp}_{int(seed)}")
    p_join, p_seg = base + ".mp4", base + "_seg.mp4"
    g["export_to_video"](frames[ctx_n:], p_seg, fps=int(fps))
    _write_joined(src, w, h, ti - ctx_n, joined_head, p_join, fps)

    # ---- 音声: 元の [0, t) ＋ 新しい音の t 以降（短いクロスフェード）----
    if r.get("audio") is not None:
        try:
            sr = int(r.get("sr") or _audio_sr())
            na = g["_audio_array"](r["audio"])
            if na.shape[1] == 1:
                na = np.repeat(na, 2, axis=1)
            off = int(round(ctx_n / fps * sr))
            seg_a = na[off:]
            g["_mux_audio"](p_seg, seg_a, sr)
            pre = _read_audio(src, sr, 0.0, t_cut) if has_audio else None
            n_pre = int(round(t_cut * sr))
            if pre is None:
                pre = np.zeros((n_pre, 2), np.float32)
            pre = pre[:n_pre]
            if pre.shape[0] < n_pre:
                pre = np.concatenate([pre, np.zeros((n_pre - pre.shape[0], 2), np.float32)])
            x = int(round(AUDIO_XFADE_MS / 1000.0 * sr))
            if x > 1 and pre.shape[0] >= x and seg_a.shape[0] >= x and has_audio:
                wgt = np.linspace(0.0, 1.0, x, dtype=np.float32)[:, None]
                # 新しい音の t の直前ぶん（文脈の描き直しの最後）と元の音の最後を混ぜる
                tail_new = na[off - x:off] if off >= x else seg_a[:x]
                pre[-x:] = pre[-x:] * (1.0 - wgt) + tail_new * wgt
            g["_mux_audio"](p_join, np.concatenate([pre, seg_a]), sr)
        except Exception as e:                                    # noqa: BLE001
            g["log"](f"⚠️ Retake の音声をつなげませんでした: {e}")
    info = {"src": os.path.basename(src), "t": round(t_cut, 4), "frame": int(ti), "ctx": ctx_n,
            "new_frames": int(nf - ctx_n), "audio_ctx": int(aud.shape[-1]) if aud is not None else 0,
            "extend": bool(extend), "shift": round(shift_sec, 4), "tone": bool(tone), "module": f"{NAME} {VERSION}"}
    for p, kind in ((p_join, "joined"), (p_seg, "segment")):
        try:
            meta = g["build_meta"](mode, prompt, w, h, "", (nf - ctx_n) / fps, nf, steps, int(seed),
                                   g["turbo_key"](), float(g["_LORA_STATE"].get("strength", 1.0)), refs_by_kind,
                                   float(r.get("sec", 0.0)), float(r.get("peak", 0.0)))
            meta["retake"] = dict(info, kind=kind)
            g["write_meta"](p, meta)
        except Exception as e:                                    # noqa: BLE001
            g["log"](f"⚠️ Retake のメタを書けませんでした: {e}")
        if not out_dir and g.get("SAVE_TO_DRIVE") and g.get("OUT_DIR"):
            try:
                import shutil
                shutil.copy2(p, os.path.join(g["OUT_DIR"], os.path.basename(p)))
            except Exception as e:                                # noqa: BLE001
                g["log"](f"⚠️ Drive へ写せませんでした: {e}")
    sec = time.time() - t0
    lines.append(T("✅ Retake 完了（{v0} 秒）: つないだもの {v1} ／ 新しい部分 {v2}", v0=f"{sec:.0f}",
                   v1=os.path.basename(p_join), v2=os.path.basename(p_seg)))
    try:
        torch.cuda.empty_cache()
    except Exception:                                             # noqa: BLE001
        pass
    yield ("\n".join(lines), dict(joined=p_join, seg=p_seg, info=info, sec=sec, peak=r.get("peak")))


# ------------------------------------------------------------------
#  0.3.0 元の動画から引き継ぐ（人物・場所・設定）
# ------------------------------------------------------------------
_SEC_NAMES = ("subject_definitions", "summary", "retention_analysis", "detailed_description",
              "overall_soundscape", "non_diegetic_music", "integrated_multimodal_description")


def _sections(text):
    """H3 の節（`名前:` の行で始まる）→ (順番の名前の並び, {名前: 中身})。節が無ければ ([], {})"""
    import re
    pat = re.compile(r"^\s*(" + "|".join(_SEC_NAMES) + r")\s*:\s*$", re.M)
    hits = list(pat.finditer(text or ""))
    order, body = [], {}
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        order.append(m.group(1))
        body[m.group(1)] = text[m.end():end].strip()
    return order, body


def _sentences(text):
    import re
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+(?=[A-Z<\[])", (text or "").strip()) if x.strip()]


def compose_prompt(original, action):
    """元のプロンプト＋「挙動だけ」の文 → 続きのプロンプト。action が節の見出しを持つ（全文を書いた）ならそのまま返す。
    人物の定義・保持の分析・音の節は元のまま。summary と detailed_description は、元から場所・光・構図・カメラ・終わり方の文だけ残して
    間に action を入れる。元が節の形でなければ「同じ人・同じ場所」の一文を前に付けるだけ"""
    action = (action or "").strip()
    order, sec = _sections(original or "")
    if not action or _sections(action)[0]:
        return action or (original or "")
    if "detailed_description" not in sec:
        return ("The same people in the same place as before, continuing directly from the previous moment. " + action)
    out = {}
    for k in order:
        out[k] = sec[k]
    # summary: 先頭のタグ（[reference generation] など）＋場所の文（最初の 1 文）＋続きの一文
    sm = sec.get("summary", "")
    tag = ""
    if sm.startswith("["):
        tag, _, sm = sm.partition("]")
        tag = tag + "] "
        sm = sm.strip()
    ss = _sentences(sm)
    keep = [x for x in ss if "same" in x.lower() and ("face" in x.lower() or "people" in x.lower() or "person" in x.lower())]
    out["summary"] = (tag + (ss[0] + " " if ss else "")
                      + "The shot continues directly from the previous moment, with the same people in the same place. "
                      + " ".join(keep)).strip()
    # detailed_description: [Shot 1] の前（光・場所）＋構図の文＋挙動＋カメラ・終わり方の文
    dd = sec["detailed_description"]
    pre, mark, post = dd.partition("[Shot 1]")
    if not mark:
        pre, post = "", dd
    ps = _sentences(post)
    frame = ps[0] if ps else ""
    tail = [x for x in ps[1:] if ("camera" in x.lower() or x.lower().startswith("the shot ends")
                                  or x.lower().startswith("hands stay"))]
    out["detailed_description"] = " ".join(y for y in (pre.strip(), "[Shot 1] " + ("The same framing continues — " + frame if frame else "").strip(),
                                                        action, " ".join(tail)) if y).replace("  ", " ")
    return "\n\n".join(f"{k}:\n{out[k]}" for k in order)


def _meta_settings(src):
    g = _g()
    m = g["read_meta"](src) or {}
    mode = g["SHORT_TO_MODE"].get(str(m.get("mode") or ""), str(m.get("mode") or "")) or None
    return m, mode


def tone_match(frames, ref_frames):
    """0.3.1 frames（PIL のリスト）の明るさを ref_frames（(N,H,W,3) uint8）の平均に合わせる → (新しいリスト, 最初と最後の倍率)"""
    from PIL import Image
    from scipy.ndimage import median_filter

    def luma(a):
        a = np.asarray(a, dtype=np.float32)[::8, ::8]
        return float((a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114).mean())
    if not frames:
        return frames, (1.0, 1.0)
    ref = float(np.mean([luma(f) for f in ref_frames]))
    ys = np.array([luma(f) for f in frames], dtype=np.float32)
    trend = median_filter(ys, size=min(TONE_WIN, len(ys) | 1), mode="nearest")
    gain = np.clip(ref / np.maximum(trend, 1e-3), *TONE_CLIP)
    out = []
    for f, gg in zip(frames, gain):
        if abs(gg - 1.0) < 0.003:
            out.append(f)
            continue
        out.append(Image.fromarray(np.clip(np.asarray(f, dtype=np.float32) * float(gg), 0, 255).astype(np.uint8)))
    return out, (float(gain[0]), float(gain[-1]))


def retake(src, t, add_sec, prompt, seed, mode=None, refs_by_kind=None, steps=None, use_audio=True, extend=False,
           shift=False, out_dir=None, inherit=False, tone=True):
    """Retake の入口。inherit=True なら元の動画のメタからモード・RefMod・Turbo・Steps を引き継ぎ、
    prompt が「挙動だけ」なら元のプロンプトと合わせる（compose_prompt）。生成が終われば本体の選択は元に戻す"""
    g = _g()
    T = _T
    if not inherit:
        yield from _retake_core(src, t, add_sec, prompt, seed, mode, refs_by_kind, steps, use_audio, extend, shift, out_dir, tone)
        return
    m, m_mode = _meta_settings(src)
    notes = []
    if not m.get("prompt"):
        notes.append(T("⚠️ 元の動画にメタ（プロンプト）が無いので引き継げません。書いたプロンプトのまま作ります"))
        yield ("\n".join(notes), None)
        yield from _retake_core(src, t, add_sec, prompt, seed, mode, refs_by_kind, steps, use_audio, extend, shift, out_dir, tone)
        return
    full = compose_prompt(str(m.get("prompt")), prompt)
    if full != (prompt or "").strip():
        notes.append(T("🧩 元のプロンプトの人物・場所・構図・音を残し、書いた挙動を入れて続きのプロンプトを組みました"))
    mode = m_mode or mode
    key0 = g["turbo_key"]()
    str0 = float(g["_LORA_STATE"].get("strength", 1.0))
    m_key = str(m.get("lora") or "")
    m_str = float(m.get("lora_strength", 1.0) or 1.0)
    steps = int(m.get("steps") or steps or 4)
    rm = g.get("_REFMOD")
    rm0 = None
    try:
        if m_key and m_key in (g.get("TURBO_CATALOG") or {}) and m_key != key0:
            g["install_turbo_lora"](m_key, verbose=False)
        if m_key:
            g["set_turbo_strength"](m_str)
        notes.append(T("   引き継ぎ: モード {v0} / Turbo {v1} × {v2} / Steps {v3}", v0=m.get("mode"), v1=m_key or "?",
                       v2=f"{m_str:g}", v3=steps))
        mr = m.get("refmods") or None
        if isinstance(rm, dict) and mr and g["is_ref_mode"](mode):
            names = [n for n in (mr.get("names") or [])
                     if os.path.isfile(os.path.join(g.get("REFMOD_DIR", ""), n + ".safetensors"))]
            miss = [n for n in (mr.get("names") or []) if n not in names]
            rm0 = {k: (list(v) if isinstance(v, list) else (dict(v) if isinstance(v, dict) else v))
                   for k, v in rm.items() if k in ("sel", "strength", "each", "cap")}
            rm.update(sel=names, strength=float(mr.get("strength", 1.0) or 1.0), each=dict(mr.get("each") or {}),
                      cap=int(mr.get("cap") or 0))
            notes.append(T("   RefMod: {v0}", v0=" / ".join(names) or "—"))
            if miss:
                notes.append(T("⚠️ 見つからない RefMod があります（無しで作ります）: {v0}", v0=" / ".join(miss)))
        yield ("\n".join(notes), None)
        last = ""
        for st, r in _retake_core(src, t, add_sec, full, seed, mode, refs_by_kind, steps, use_audio, extend, shift, out_dir, tone):
            last = st or last
            if r is not None:
                r = dict(r, prompt=full)
            yield ("\n".join(notes + [last]), r)
    finally:
        if rm0 is not None:
            rm.update(rm0)
        try:
            if g["turbo_key"]() != key0:
                g["install_turbo_lora"](key0, verbose=False)
            g["set_turbo_strength"](str0)
        except Exception as e:                                    # noqa: BLE001
            g["log"](f"⚠️ 元の Turbo LoRA に戻せませんでした: {e}")



def _write_joined(src, w, h, n_pre, new_frames, out, fps):
    """元の 0〜n_pre−1 コマ ＋ new_frames を 1 本の mp4 に（元のコマは ffmpeg からそのまま流す＝全部をメモリに載せない）"""
    ff = _g()["_ffmpeg_exe"]()
    enc = subprocess.Popen([ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
                            "-r", f"{fps:g}", "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "17",
                            "-preset", "medium", out], stdin=subprocess.PIPE)
    try:
        if n_pre > 0:
            dec = subprocess.Popen([ff, "-v", "error", "-i", src, "-vf", f"select='lt(n\\,{int(n_pre)})'", "-vsync", "0",
                                    "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-"], stdout=subprocess.PIPE)
            per = w * h * 3
            got = 0
            while got < n_pre:
                buf = dec.stdout.read(per)
                if len(buf) < per:
                    break
                enc.stdin.write(buf)
                got += 1
            dec.stdout.close()
            dec.wait()
        for f in new_frames:
            enc.stdin.write(np.asarray(f, dtype=np.uint8).tobytes())
    finally:
        enc.stdin.close()
        enc.wait()


# ------------------------------------------------------------------
#  本体との約束
# ------------------------------------------------------------------
def setup(ctx):
    _ST["ctx"] = ctx
    ctx.provide("media_context_retake", retake)
    ctx.provide("media_context_audio", audio_context)


def build_slot(ctx, slot):
    return None


def wire(ctx, comps):
    return None


if __name__ == "__main__":                                        # 構文の確認用
    print(NAME, VERSION, json.dumps(sorted(I18N))[:80])
