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
0.3.2: 利用者所見「明るさは良くなったが色調が微妙にずれる」。測ると（183 の出力）赤みが増え（R/G 文脈 1.130 → 新しい部分 1.161／1.195）、
       同じ倍率で明るくすると色の広がり（Lab の a・b の標準偏差）も 8.29 → 9.33／9.98 と濃くなっていた。
       → 明るさ合わせを **R・G・B 別の倍率**に（色かぶりも一緒に合わせる）＋ **色の広がり**を文脈に合わせる（各コマの平均の色のまわりで
         a・b を縮める／広げる。流れは中央値）。倍率の範囲を 0.75〜1.35 に広げた（終わりの方で G が 1.3 倍要った）。
         183 の出力（新しい部分の前半／後半）で: R/G 1.163／1.197 → 1.139／1.144（文脈 1.131）、B/G 1.048／1.044 → 1.030／1.028（1.033）、
         広がり 8.44／8.55 → 8.20／8.25（8.24）、明るさ 54.0／50.1 → 60.4／60.4（60.8）、白飛び 0.07% 以下。
       追加プロンプトの時刻: 新しいクリップは「文脈の始まり＝t−22 コマ」が 0 秒。inherit で挙動の文に書いた時刻（「6-8s」「00:06.000」の形）は
       **つないだ動画の時刻**として読み、新しいクリップの時刻へずらす（shift_times）
0.3.3: 利用者所見「フリッカーっぽい繋ぎ目がわかる」。測ると（183 の出力）元と新しい絵を 22 コマかけて混ぜている間、
       鮮鋭度が 120 → 83〜90 へ落ちて t で 98 に戻る（同じ場面の別の描画どうしを重ねると細部がずれて柔らかくなる＝ふわっと沈んで戻る）。
       → 混ぜるコマ数を選べるように（blend: 0＝混ぜずに t で切り替え、既定は 22 のまま）。計測のとき（out_dir 指定）は
         新しいクリップを混ぜる前の全コマで `_raw.mp4` にも書く＝1 回の生成から混ぜ方を何通りも作って比べられる（計測セル 184）
0.3.4: セル184 の結果（B22／B8／B3／CUT）: 鮮鋭度の谷 0.67／0.75／0.69／0.93、t のコマ差の山 1.40／1.22／1.32／1.63 倍。
       CUT の t の前後のコマを見ると、平均の明るさ・色は合っているのに**影が沈み、明るい所が少し明るい**（明暗の幅が広い）。
       灰色の分位: 元 p10 2.9・p25 9.6・p90 139 → 新 0.9・4.1・144。掛け算（平均）だけでは直らない。
       → **明暗の分布（トーンカーブ）合わせ**を足した: 各コマの明るさの分位（1/5/10/25/50/75/90/95/99%、25 コマの中央値の流れ）を
         文脈の分位へ写す折れ線で明るさを直し、RGB には比で掛ける（暗部 16 未満は差を足す＝比が暴れない）。順は RGB 別の倍率 → カーブ → 色の広がり。
         184 の CUT（960 幅）で: 新の p10/p25/p90 0.9/4.1/144 → 3.1/10.1/138（元 2.9/9.6/139）、t のコマ差 5.07 → 4.34（ふだん 3.61）
0.3.5: セル185（184 の生成に 0.3.4 の合わせを掛け直し）: 鮮鋭度の谷 B22 0.67／B8 0.75／B3 0.69／CUT 0.83、コマ差の山 1.52／1.51／1.51／1.42 倍。
       混ぜる案だけ山が増えたのは、合わせを新しい部分（t の後）にしか掛けず、描き直しの 22 コマは元のままだったため
       （B8 で混ぜ終わり 60.5 → t の後 58.8 と明るさが食い違う）→ 描き直しの 22 コマも含めてクリップ全体を文脈に合わせる
0.4.0: **RETAKE タブ**（利用者合意: タブを新設・LIBRARY に「↪ RETAKE へ送る」・元の設定を引き継いで挙動だけ書く最小版）。
       並びは SEGMENTS の写し（左 SOURCE と撮り直す位置／右 続きの挙動・足す長さ・Seed・引き継ぎ・RETAKE・RESULT）、書式は
       本体の CSS から SEGMENTS／LIBRARY の規則を id を替えて写す（_mirror_css）。本体は module_slot("lib_send")・("main_tabs") と
       comps の main_tabs・mode・steps を用意する。生成は concurrency_id="generate"（本体の生成と直列）
0.4.1: 利用者の質問「元のプロンプトが 15 秒まで時刻つきで書いてあって、6 秒からリテイクして 6s〜と書いても成功するか」→ 2 つ直した:
       ①元のプロンプトの時刻つきの文（0-5s: … など）を続きのプロンプトへ持ち込まない（元の時刻は新しいクリップの時刻と食い違い、
         序盤の動きを演じ直す元になる）。構図・カメラ・終わり方の文も、時刻を含むものは外す
       ②挙動の文に書いた時刻の終わり（例 6-12s → 12 秒）まで入るように「足す長さ」を自動で延ばす（上限 14 秒）
0.5.0: 利用者要望（2026-10-24）: ①Turbo LoRA を選べる（既定「元と同じ」。選んだら Steps はその LoRA の既定＝本体 steps_for_lora）
       ②使っている RefMod を絵で出す（CREATE の RefMod ピッカーと同じタイル・番号。#refmod-pick の書式を写す）
       ③処理の状況を他のタブと同じ STATUS の箱に出す（#status-panel の書式を写す）
       ④Steps も選べる（0＝自動: 元と同じ／選んだ Turbo の既定。Turbo を選ぶとその既定が入る＝CREATE と同じ動き）
0.3.6: セル185 v2（全体を合わせた後）: 鮮鋭度の谷 B22 0.62／B8 0.67／B3 0.65／CUT 0.80、コマ差の山 1.42／**1.19**／1.21／1.46 倍。
       利用者の目「B8 が一番改善」→ **既定の混ぜ方を最後の 8 コマに**（BLEND_DEFAULT）
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
VERSION = "0.5.0"
API = 1

AUDIO_LAT_PER_SEC = 40.0                # 音声 VAE の潜在の速さ（diffusers の MINIMAX_H3_AUDIO_LATENTS_PER_SECOND）
AUDIO_WIN_BEFORE = 4.0                  # 音声の文脈を取るとき、t の何秒前からエンコードするか（端の癖を文脈から遠ざける）
AUDIO_WIN_AFTER = 0.5                   # t の後ろも少し含めてエンコードする（窓の終わりの端の癖を文脈に入れない）
AUDIO_XFADE_MS = 20                     # t で元の音と新しい音をつなぐ短いクロスフェード
POLL_SEC = 0.5
BLEND_DEFAULT = 8                       # 0.3.6 元と描き直しを混ぜるコマ数（t の直前の 8 コマ。セル185 v2・利用者の目で決定）
TONE_WIN = 25                           # 0.3.1 明るさの流れを見る幅（コマ。中央値）
TONE_PCT = (1, 5, 10, 25, 50, 75, 90, 95, 99)   # 0.3.4 トーンカーブを合わせる明るさの分位（%）
TONE_DARK = 16.0                        # 0.3.4 これより暗い所は比ではなく差で直す（比が暴れてノイズが立つのを防ぐ）
TONE_CLIP = (0.75, 1.35)                # 0.3.1 明るさを合わせる倍率の範囲（0.3.2 で 0.8〜1.25 から広げた: 赤みが強い終わりの方で G が 1.3 倍要った）
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
    "   時刻の指定 {v0} か所を、新しいクリップの時刻へずらしました（つないだ動画の時刻として読みます）": {
        "en": "   Shifted {v0} time marks to the new clip's timeline (read as times in the joined video)",
        "zh": "   已将 {v0} 处时间指定换算到新片段的时间轴（按拼接后视频的时间理解）",
        "ko": "   시간 지정 {v0} 곳을 새 클립의 시간으로 옮겼습니다(이어 붙인 영상의 시간으로 읽습니다)"},
    "   書いた時刻（〜{v0} 秒）まで入るように、足す長さを {v1} 秒にしました": {
        "en": "   Set the length to add to {v1} s so the written times (up to {v0} s) fit",
        "zh": "   为容纳所写的时间（至 {v0} 秒），已将追加长度设为 {v1} 秒",
        "ko": "   쓴 시간(~{v0} 초)까지 들어가도록 추가 길이를 {v1} 초로 했습니다"},
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
                 shift=False, out_dir=None, tone=True, blend=None):
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
            # 0.3.5 描き直しの 22 コマも一緒に合わせる（新しい部分だけ直すと、混ぜた所の終わり＝描き直しの最後のコマと
            #       t の後のコマで明るさが食い違い、混ぜる案で t に段差が出た。セル185: B22/B8/B3 のコマ差の山 1.51 倍）
            frames, (g0, g1) = tone_match(frames, ctx_px)
            if abs(g0 - 1.0) >= 0.01 or abs(g1 - 1.0) >= 0.01:
                lines.append(T("   明るさ合わせ: 新しい部分を文脈の明るさに合わせました（×{v0}〜×{v1}）", v0=f"{g0:.2f}", v1=f"{g1:.2f}"))
        except Exception as e:                                    # noqa: BLE001
            lines.append(T("⚠️ 明るさ合わせに失敗しました（そのまま書き出します）: {v0}", v0=f"{e}"))
    # 先頭 22 コマ（文脈の描き直し）のうち最後の L コマを元のコマと滑らかに混ぜる。L＝0 なら t で切り替え（元は t まで全部使う）
    L = min(ctx_n, BLEND_DEFAULT) if blend is None else max(0, min(ctx_n, int(blend)))
    joined_head = g["_blend_head"](frames[ctx_n - L:], ctx_px[ctx_n - L:], L) if L > 0 else frames[ctx_n:]
    stamp = datetime.datetime.now().strftime("%H%M%S")
    od = str(out_dir) if out_dir else "/content"
    os.makedirs(od, exist_ok=True)
    base = os.path.join(od, f"minimax_h3_retake_{stamp}_{int(seed)}")
    p_join, p_seg = base + ".mp4", base + "_seg.mp4"
    g["export_to_video"](frames[ctx_n:], p_seg, fps=int(fps))
    _write_joined(src, w, h, ti - L, joined_head, p_join, fps)
    p_raw = None
    if out_dir:                                                   # 計測用: 混ぜる前の全コマ（文脈の描き直しを含む）
        p_raw = base + "_raw.mp4"
        try:
            g["export_to_video"](frames, p_raw, fps=int(fps))
        except Exception as e:                                    # noqa: BLE001
            g["log"](f"⚠️ _raw.mp4 を書けませんでした: {e}")
            p_raw = None

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
            "extend": bool(extend), "shift": round(shift_sec, 4), "tone": bool(tone), "blend": int(L),
            "module": f"{NAME} {VERSION}"}
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
    yield ("\n".join(lines), dict(joined=p_join, seg=p_seg, raw=p_raw, info=info, sec=sec, peak=r.get("peak")))


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
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+(?=[A-Z<\[\d])", (text or "").strip()) if x.strip()]


_TIME_RE = None


def _has_time(text):
    """時刻の指定（6-8s / 0:06 / At 00:06.000 の形）を含むか"""
    import re
    global _TIME_RE
    if _TIME_RE is None:
        _TIME_RE = re.compile(r"(?<![\d.:])\d+(?:\.\d+)?\s*[-–〜~]\s*\d+(?:\.\d+)?\s*s\b|(?<![\d.:])\d{1,2}:\d{2}(?:\.\d{1,3})?(?![\d:])")
    return bool(_TIME_RE.search(text or ""))


def _time_end(text):
    """挙動の文に書いた時刻の最大（秒）。無ければ None"""
    import re
    ends = [float(b) for _a, b in re.findall(r"(?<![\d.:])(\d+(?:\.\d+)?)\s*[-–〜~]\s*(\d+(?:\.\d+)?)\s*s\b", text or "")]
    ends += [int(mm) * 60 + float(ss) for mm, ss in re.findall(r"(?<![\d.:])(\d{1,2}):(\d{2}(?:\.\d{1,3})?)(?![\d:])", text or "")]
    return max(ends) if ends else None


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
    # 0.4.1 時刻つきの文（0-5s: … など。元のタイムラインの動き）は持ち込まない
    ps = [x for x in _sentences(post) if not _has_time(x)]
    frame = ps[0] if ps else ""
    tail = [x for x in ps[1:] if ("camera" in x.lower() or x.lower().startswith("the shot ends")
                                  or x.lower().startswith("hands stay"))]
    if _has_time(pre):
        pre = " ".join(x for x in _sentences(pre) if not _has_time(x))
    out["detailed_description"] = " ".join(y for y in (pre.strip(), "[Shot 1] " + ("The same framing continues — " + frame if frame else "").strip(),
                                                        action, " ".join(tail)) if y).replace("  ", " ")
    return "\n\n".join(f"{k}:\n{out[k]}" for k in order)


def _steps_for(key, mode):
    """Turbo LoRA → Steps（本体 steps_for_lora。無ければカタログの forwards）"""
    g = _g()
    try:
        v = g["steps_for_lora"](key, False, mode)
        if v:
            return int(v)
    except Exception:                                             # noqa: BLE001
        pass
    try:
        return int((g.get("TURBO_CATALOG") or {}).get(key, {}).get("forwards") or 0) or None
    except Exception:                                             # noqa: BLE001
        return None


def _meta_settings(src):
    g = _g()
    m = g["read_meta"](src) or {}
    mode = g["SHORT_TO_MODE"].get(str(m.get("mode") or ""), str(m.get("mode") or "")) or None
    return m, mode


def tone_match(frames, ref_frames):
    """frames（PIL のリスト）の明るさ・色かぶり・色の広がりを ref_frames（(N,H,W,3) uint8 RGB）に合わせる
    → (新しいリスト, (最初の明るさの倍率, 最後の明るさの倍率))
    0.3.1 明るさ（RGB に同じ倍率）→ 0.3.2 R・G・B 別の倍率＋Lab の a・b の広がり → 0.3.4 ＋明暗の分布（トーンカーブ）。
    流れは 25 コマの中央値（段差の位置を保つ）"""
    import cv2
    from PIL import Image
    from scipy.ndimage import median_filter
    if not frames:
        return frames, (1.0, 1.0)

    def small(a):
        return np.asarray(a, dtype=np.float32)[::8, ::8]

    def spread(a):
        lab = cv2.cvtColor(np.clip(a / 255.0, 0, 1).astype(np.float32), cv2.COLOR_RGB2Lab)
        return float(np.sqrt(lab[..., 1].var() + lab[..., 2].var()))
    win = min(TONE_WIN, len(frames) | 1)
    ref_rgb = np.mean([small(f).reshape(-1, 3).mean(0) for f in ref_frames], axis=0)
    ref_sp = float(np.mean([spread(small(f)) for f in ref_frames]))
    rgb = np.array([small(f).reshape(-1, 3).mean(0) for f in frames], dtype=np.float32)
    gains = np.clip(ref_rgb[None] / np.maximum(median_filter(rgb, size=(win, 1), mode="nearest"), 1e-3), *TONE_CLIP)
    # 0.3.4 明暗の分布（トーンカーブ）: 倍率を掛けたあとの明るさの分位を文脈の分位へ写す
    P = np.array(TONE_PCT, dtype=np.float32)
    wy = np.array([0.299, 0.587, 0.114], dtype=np.float32)
    ref_pc = np.percentile(np.concatenate([(small(f) @ wy).ravel() for f in ref_frames]), P)
    pc = np.array([np.percentile((small(f) * gains[i]) @ wy, P) for i, f in enumerate(frames)], dtype=np.float32)
    pc = median_filter(pc, size=(win, 1), mode="nearest")

    def curve(a, p):
        y = a @ wy
        xs = np.maximum.accumulate(np.concatenate([[0.0], p, [255.0]]) + np.arange(len(p) + 2) * 1e-3)
        ys = np.concatenate([[0.0], ref_pc, [255.0]])
        y2 = np.interp(y, xs, ys).astype(np.float32)
        r = (y2 / np.maximum(y, 1e-3))[..., None]
        return np.where((y <= TONE_DARK)[..., None], a + (y2 - y)[..., None], a * r)
    sp = np.array([spread(curve(small(f) * gains[i], pc[i])) for i, f in enumerate(frames)], dtype=np.float32)
    sat = np.clip(ref_sp / np.maximum(median_filter(sp, size=win, mode="nearest"), 1e-3), *TONE_CLIP)
    out = []
    for i, (f, gg, ss) in enumerate(zip(frames, gains, sat)):
        a = curve(np.asarray(f, dtype=np.float32) * gg[None, None, :], pc[i])
        if abs(float(ss) - 1.0) >= 0.005:
            lab = cv2.cvtColor(np.clip(a / 255.0, 0, 1).astype(np.float32), cv2.COLOR_RGB2Lab)
            for c in (1, 2):
                m = float(lab[..., c].mean())
                lab[..., c] = m + (lab[..., c] - m) * float(ss)
            a = cv2.cvtColor(lab, cv2.COLOR_Lab2RGB) * 255.0
        out.append(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)))
    lum = gains @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    return out, (float(lum[0]), float(lum[-1]))


def shift_times(text, off):
    """挙動の文の時刻（つないだ動画の時刻）を新しいクリップの時刻（文脈の始まりが 0 秒）へずらす。
    「6-8s」「6.5〜8s」の形と「00:06」「0:06.500」の形（分:秒）を直す。0 秒より前は 0 にする"""
    import re
    off = float(off)
    if off <= 0 or not text:
        return text, 0

    def fmt(x):
        return f"{max(0.0, x):.2f}".rstrip("0").rstrip(".")
    n = [0]

    def r1(m):
        n[0] += 1
        return f"{fmt(float(m.group(1)) - off)}-{fmt(float(m.group(2)) - off)}s"
    text = re.sub(r"(?<![\d.:])(\d+(?:\.\d+)?)\s*[-–〜~]\s*(\d+(?:\.\d+)?)\s*s\b", r1, text)

    def r2(m):
        n[0] += 1
        sec = max(0.0, int(m.group(1)) * 60 + float(m.group(2)) - off)
        dec = len(m.group(2).split(".")[1]) if "." in m.group(2) else 0
        if dec == 0 and abs(sec - round(sec)) > 1e-6:
            dec = 3                                               # ずらして端数が出たら .mmm を付ける
        ss = f"{sec % 60:0{3 + dec if dec else 2}.{dec}f}"
        return f"{int(sec // 60):0{len(m.group(1))}d}:{ss}"
    text = re.sub(r"(?<![\d.:])(\d{1,2}):(\d{2}(?:\.\d{1,3})?)(?![\d:])", r2, text)
    return text, n[0]


def retake(src, t, add_sec, prompt, seed, mode=None, refs_by_kind=None, steps=None, use_audio=True, extend=False,
           shift=False, out_dir=None, inherit=False, tone=True, blend=None, turbo=None):
    """0.5.0 turbo … Turbo LoRA の名前（空なら inherit のときは元のもの、そうでなければいまのもの）。選ぶと Steps はその LoRA の既定。
    Retake の入口。inherit=True なら元の動画のメタからモード・RefMod・Turbo・Steps を引き継ぎ、
    prompt が「挙動だけ」なら元のプロンプトと合わせる（compose_prompt）。生成が終われば本体の選択は元に戻す"""
    g = _g()
    T = _T
    if not inherit:
        if not turbo:
            yield from _retake_core(src, t, add_sec, prompt, seed, mode, refs_by_kind, steps, use_audio, extend, shift, out_dir, tone, blend)
            return
        key0 = g["turbo_key"]()
        str0 = float(g["_LORA_STATE"].get("strength", 1.0))
        try:
            if turbo != key0:
                g["install_turbo_lora"](turbo, verbose=False)
            g["set_turbo_strength"](1.0)
            st_ = steps or _steps_for(turbo, mode)
            yield from _retake_core(src, t, add_sec, prompt, seed, mode, refs_by_kind, st_, use_audio, extend, shift, out_dir, tone, blend)
        finally:
            try:
                if g["turbo_key"]() != key0:
                    g["install_turbo_lora"](key0, verbose=False)
                g["set_turbo_strength"](str0)
            except Exception as e:                                # noqa: BLE001
                g["log"](f"⚠️ 元の Turbo LoRA に戻せませんでした: {e}")
        return
    m, m_mode = _meta_settings(src)
    user_steps = int(steps) if steps else 0                       # 0.5.0 画面で選んだ Steps（0＝自動）
    notes = []
    if not m.get("prompt"):
        notes.append(T("⚠️ 元の動画にメタ（プロンプト）が無いので引き継げません。書いたプロンプトのまま作ります"))
        yield ("\n".join(notes), None)
        yield from _retake_core(src, t, add_sec, prompt, seed, mode, refs_by_kind, steps, use_audio, extend, shift, out_dir, tone, blend)
        return
    act = prompt
    if prompt and not _sections(prompt)[0]:
        try:
            _w, _h, _n, _f, _a = g["_probe_video"](src)
            fpsx = float(g.get("FPS", 24))
            ti = int(_n) if extend else int(round(float(t) * fpsx))
            act, nt = shift_times(prompt, (ti - int(g.get("MOTION_CTX_FRAMES", 22))) / fpsx)
            if nt:
                notes.append(T("   時刻の指定 {v0} か所を、新しいクリップの時刻へずらしました（つないだ動画の時刻として読みます）", v0=nt))
            te = _time_end(prompt)                                # 0.4.1 書いた時刻の終わりまで入るように延ばす
            need = (te - ti / fpsx + 0.25) if te is not None else 0.0
            if need > float(add_sec):
                add_sec = min(14.0, need)
                notes.append(T("   書いた時刻（〜{v0} 秒）まで入るように、足す長さを {v1} 秒にしました", v0=f"{te:g}", v1=f"{add_sec:.1f}"))
        except Exception:                                         # noqa: BLE001
            act = prompt
    full = compose_prompt(str(m.get("prompt")), act)
    if full != (prompt or "").strip():
        notes.append(T("🧩 元のプロンプトの人物・場所・構図・音を残し、書いた挙動を入れて続きのプロンプトを組みました"))
    mode = m_mode or mode
    key0 = g["turbo_key"]()
    str0 = float(g["_LORA_STATE"].get("strength", 1.0))
    m_key = str(m.get("lora") or "")
    m_str = float(m.get("lora_strength", 1.0) or 1.0)
    steps = int(m.get("steps") or steps or 4)
    if turbo and turbo != m_key:                                  # 0.5.0 選んだ Turbo LoRA（強さ 1.0、Steps はその LoRA の既定）
        m_key, m_str = str(turbo), 1.0
        steps = _steps_for(turbo, mode) or steps
    if user_steps > 0:                                            # 0.5.0 Steps を選んだらそれを使う
        steps = user_steps
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
        for st, r in _retake_core(src, t, add_sec, full, seed, mode, refs_by_kind, steps, use_audio, extend, shift, out_dir, tone, blend):
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
#  0.4.0 RETAKE タブ（UI）。並びは SEGMENTS タブの写し（左 2：右 1）。書式も SEGMENTS の規則を id を替えて写す（_mirror_css）
# ------------------------------------------------------------------
_MIRROR = {                                                       # SEGMENTS / LIBRARY の id → RETAKE の id
    "#seg-left": ["#rt-left"], "#seg-right": ["#rt-right"],
    "#seg-preview-box": ["#rt-src-box", "#rt-out-box"], "#seg-detail": ["#rt-detail"],
    "#seg-act": ["#rt-act", "#rt-time"], "#seg-reseed": ["#rt-extend", "#rt-inherit"],
    "#seg-concat-btn": ["#rt-pos-btn", "#rt-run-btn"], "#seg-msg": ["#rt-msg"], "#seg-note": ["#rt-note"],
    "#seg-len": ["#rt-t", "#rt-add", "#rt-steps"],
    "#lib-up-btn": ["#lib-rt-btn"],
    "#status-panel": ["#rt-status"], "#refmod-pick": ["#rt-refmods"], "#lora-dd": ["#rt-turbo"],   # 0.5.0
}
CSS = ""                                                          # setup で本体の CSS から作る（本体と同じ値を二重に持たない）
CSS_EXTRA = """
/* RETAKE: 文字の欄（続きの挙動・Seed）の見出しは、同じ箱のスライダー（#rt-add＝SEGMENT の写し）と同じ書式 */
#rt-action label, #rt-action label > span:first-child,
#rt-seed label, #rt-seed label > span:first-child {
    font-size: 12px !important; color: var(--h3-muted) !important;
    letter-spacing: 0.04em !important; font-weight: 400 !important;
}
#rt-action textarea, #rt-seed input { color: var(--h3-text3) !important; font-size: 13px !important; letter-spacing: 0 !important; }
#rt-run-btn { margin-top: 8px !important; }
/* 左の列は伸ばさない（SEGMENTS の左は一覧が伸びるが、RETAKE の左は SOURCE と位置の箱だけ。伸ばすと間が空く） */
#rt-left { justify-content: flex-start !important; }
/* 0.5.0 STATUS と RefMod の箱は、ほかの箱（SEGMENTS の写し＝列の内側に左右 12px）と左右の端をそろえる */
#rt-status, #rt-refmods { margin-left: 12px !important; margin-right: 12px !important; width: calc(100% - 24px) !important; min-width: 0 !important; flex-grow: 0 !important; }
#rt-left > * { flex: 0 0 auto !important; }
#rt-time > *, #rt-act > * { margin-top: 0 !important; }
"""


def _mirror_css(css):
    """本体の CSS から、_MIRROR の id だけで書かれた規則を写す（本体 _mirror_lora_css と同じ考え。コードは写していない）"""
    import re
    body = re.sub(r"/\*.*?\*/", "", css or "", flags=re.S)
    out, i, n = [], 0, len(body)
    while i < n:
        j = body.find("{", i)
        if j < 0:
            break
        sel = body[i:j].strip()
        depth, k = 1, j + 1
        while k < n and depth:
            depth += {"{": 1, "}": -1}.get(body[k], 0)
            k += 1
        block = body[j + 1:k - 1]
        i = k
        if sel.startswith("@") or "{" in block:
            continue
        keep = []
        for one in sel.split(","):
            one = one.strip()
            ids = re.findall(r"#[\w-]+", one)
            hit = [x for x in ids if x in _MIRROR]
            if not hit or any(x not in _MIRROR and x != "#lib-preview-box" for x in ids):
                continue
            outs = [one]
            for x in hit:
                outs = [o.replace(x, y) for o in outs for y in _MIRROR[x]]
            keep += outs
        if keep:
            out.append(",\n".join(dict.fromkeys(keep)) + " {" + block + "}")
    return "\n".join(out)


HELP_RT = ("LIBRARY の動画の続きを作る・途中から作り直す機能です。**元の動画のメタ**（プロンプト・モード・RefMod・Turbo・Steps）を自動で引き継ぎ、"
           "人物・場所・構図・カメラ・音はそのまま、「続きの挙動」に書いた動きやセリフだけを足します。\n"
           "時刻を書くときは**つないだ動画の時刻**で（例: 6 秒から作り直すなら `6-8s: …`）。新しいクリップの時刻へ自動で直します。\n"
           "新しいクリップは t の直前 22 コマ（約 0.9 秒）と音を引き継いで作り、t の直前 8 コマで元と混ぜてつなぎます。明るさ・色・明暗も元に合わせます。\n"
           "結果は LIBRARY に「つないだもの」と「新しい部分だけ」の 2 本で残ります（元のファイルは変わりません）")

I18N.update({
    "↪ RETAKE へ送る": {"en": "↪ Send to RETAKE", "zh": "↪ 发送到 RETAKE", "ko": "↪ RETAKE 로 보내기"},
    "撮り直す位置（秒）": {"en": "Retake from (s)", "zh": "重拍位置（秒）", "ko": "다시 찍을 위치(초)"},
    "▶ 再生位置を使う": {"en": "▶ Use playhead", "zh": "▶ 使用播放位置", "ko": "▶ 재생 위치 사용"},
    "終わりから延長する": {"en": "Extend from the end", "zh": "从结尾延长", "ko": "끝에서 이어 만들기"},
    "続きの挙動（動き・セリフ）": {"en": "What happens next (action / lines)", "zh": "接下来的动作（动作・台词）", "ko": "이어지는 동작(움직임·대사)"},
    "足す長さ（秒）": {"en": "Length to add (s)", "zh": "追加长度（秒）", "ko": "추가할 길이(초)"},
    "Seed（−1 で元＋1）": {"en": "Seed (−1 = source + 1)", "zh": "Seed（−1 为原 +1）", "ko": "Seed(−1 은 원본 +1)"},
    "元の設定を引き継ぐ": {"en": "Inherit the source settings", "zh": "继承原视频设置", "ko": "원본 설정 이어받기"},
    "🎬 RETAKE": {"en": "🎬 RETAKE", "zh": "🎬 RETAKE", "ko": "🎬 RETAKE"},
    "⏳ 生成中…": {"en": "⏳ Generating…", "zh": "⏳ 生成中…", "ko": "⏳ 생성 중…"},
    "元と同じ": {"en": "Same as source", "zh": "与原视频相同", "ko": "원본과 같음"},
    "Steps（0 で自動）": {"en": "Steps (0 = auto)", "zh": "Steps（0 为自动）", "ko": "Steps(0 은 자동)"},
    "元の動画は RefMod を使っていません": {"en": "The source video does not use RefMods", "zh": "原视频未使用 RefMod",
                                       "ko": "원본 영상은 RefMod 를 쓰지 않습니다"},
    "元の動画の RefMod（{v0} 件）": {"en": "RefMods of the source ({v0})", "zh": "原视频的 RefMod（{v0} 个）",
                                 "ko": "원본 영상의 RefMod({v0} 개)"},
    "RefMod": {"en": "RefMod", "zh": "RefMod", "ko": "RefMod"},
    "例: <Subject 2> laughs and says <d>[Japanese] …</d>（人物・場所・カメラは書かなくてよい）": {
        "en": "e.g. <Subject 2> laughs and says <d>[Japanese] …</d> (no need to describe people, place or camera)",
        "zh": "例：<Subject 2> laughs and says <d>[Japanese] …</d>（不必写人物・地点・镜头）",
        "ko": "예: <Subject 2> laughs and says <d>[Japanese] …</d>(인물·장소·카메라는 쓰지 않아도 됨)"},
    "LIBRARY で動画を選んで「↪ RETAKE へ送る」か、SOURCE に動画を入れてください。": {
        "en": "Pick a video in LIBRARY and press “↪ Send to RETAKE”, or drop a video into SOURCE.",
        "zh": "请在 LIBRARY 中选择视频并点击「↪ 发送到 RETAKE」，或把视频放入 SOURCE。",
        "ko": "LIBRARY 에서 영상을 고르고 「↪ RETAKE 로 보내기」를 누르거나, SOURCE 에 영상을 넣으세요."},
    "続きの挙動を書いてください": {"en": "Write what happens next", "zh": "请写下接下来的动作", "ko": "이어지는 동작을 써 주세요"},
    "LIBRARY でファイルを選んでください": {"en": "Select a file in LIBRARY", "zh": "请在 LIBRARY 中选择文件", "ko": "LIBRARY 에서 파일을 선택하세요"},
    "静止画は RETAKE できません（動画を選んでください）": {"en": "Stills cannot be retaken (pick a video)",
                                                 "zh": "静态图像无法 RETAKE（请选择视频）", "ko": "정지 이미지는 RETAKE 할 수 없습니다(영상을 고르세요)"},
    "長さ {v0} 秒・{v1}×{v2}・{v3} コマ": {"en": "{v0} s · {v1}×{v2} · {v3} frames", "zh": "长度 {v0} 秒・{v1}×{v2}・{v3} 帧",
                                       "ko": "길이 {v0} 초·{v1}×{v2}·{v3} 프레임"},
    "元の設定: {v0}": {"en": "Source settings: {v0}", "zh": "原设置：{v0}", "ko": "원본 설정: {v0}"},
    "メタ（プロンプト）が無い動画です。「元の設定を引き継ぐ」は使えません": {
        "en": "This video has no metadata (prompt). “Inherit the source settings” cannot be used",
        "zh": "此视频没有元数据（提示词），无法使用「继承原视频设置」",
        "ko": "메타데이터(프롬프트)가 없는 영상입니다. 「원본 설정 이어받기」를 쓸 수 없습니다"},
    "⛔ ほかの生成が終わるまでお待ちください": {"en": "⛔ Please wait until the other generation finishes",
                                       "zh": "⛔ 请等待其他生成完成", "ko": "⛔ 다른 생성이 끝날 때까지 기다려 주세요"},
    HELP_RT: {
        "en": "Make the continuation of a LIBRARY video, or re-make it from a point. The **source video's metadata** (prompt, mode, RefMods, Turbo, Steps) is inherited automatically: people, place, framing, camera and sound stay, and only the movement and lines you write in “What happens next” are added.\nWrite times in the **joined video's timeline** (e.g. to re-make from 6 s, `6-8s: …`); they are converted to the new clip's timeline automatically.\nThe new clip is made from the 22 frames (about 0.9 s) and the audio just before t, and blended with the source over the last 8 frames before t. Brightness, colour and contrast are matched to the source.\nTwo results stay in LIBRARY: the joined video and the new part only (the source file is not changed)",
        "zh": "为 LIBRARY 中的视频生成后续，或从中途重新生成。会自动继承**原视频的元数据**（提示词・模式・RefMod・Turbo・Steps），人物・地点・构图・镜头・声音保持不变，只加入你在「接下来的动作」中写的动作和台词。\n写时间时请用**拼接后视频的时间**（例：从 6 秒重做则写 `6-8s: …`），会自动换算到新片段的时间。\n新片段以 t 之前的 22 帧（约 0.9 秒）和声音为上下文生成，并在 t 之前的 8 帧与原视频混合衔接。亮度・颜色・明暗也会对齐原视频。\n结果以「拼接版」和「仅新部分」两条保存在 LIBRARY（原文件不变）",
        "ko": "LIBRARY 영상의 뒷부분을 만들거나 중간부터 다시 만듭니다. **원본 영상의 메타데이터**(프롬프트·모드·RefMod·Turbo·Steps)를 자동으로 이어받아 인물·장소·구도·카메라·소리는 그대로 두고, 「이어지는 동작」에 쓴 움직임과 대사만 더합니다.\n시간은 **이어 붙인 영상의 시간**으로 쓰세요(예: 6 초부터 다시 만들려면 `6-8s: …`). 새 클립의 시간으로 자동 변환합니다.\n새 클립은 t 직전 22 프레임(약 0.9 초)과 소리를 이어받아 만들고, t 직전 8 프레임에서 원본과 섞어 잇습니다. 밝기·색·명암도 원본에 맞춥니다.\n결과는 LIBRARY 에 「이어 붙인 것」과 「새 부분만」 2 개로 남습니다(원본 파일은 바뀌지 않습니다)"},
})

_UI = {}


def setup(ctx):
    global CSS
    _ST["ctx"] = ctx
    ctx.provide("media_context_retake", retake)
    ctx.provide("media_context_audio", audio_context)
    ctx.provide("media_context_tone", tone_match)                 # 0.3.4 計測セルが 1 回の生成から何通りも作るため
    try:
        CSS = "\n/* ---- RETAKE（media_context。SEGMENTS の写し） ---- */\n" + _mirror_css(ctx.g.get("CUSTOM_CSS", "")) + CSS_EXTRA
    except Exception:                                             # noqa: BLE001
        CSS = CSS_EXTRA
    ctx.help("retake", HELP_RT)


SLOTS = ("lib_send", "main_tabs")


def build_slot(ctx, slot):
    gr = ctx.gr
    g = ctx.g
    if slot == "lib_send":
        _UI["lib_btn"] = gr.Button("↪ RETAKE へ送る", elem_id="lib-rt-btn")
        return
    if slot != "main_tabs":
        return
    box_h = int(g.get("SEG_BOX_H", 360))
    with gr.Tab("RETAKE", id="tab-retake"):
        _UI["src"] = gr.State(None)
        with gr.Row(equal_height=True):
            with gr.Column(scale=2, elem_id="rt-left"):
                with gr.Column(elem_classes=["panel"], elem_id="rt-src-box"):
                    _UI["src_video"] = gr.Video(label="SOURCE", autoplay=False, height=box_h, elem_id="rt-src-video",
                                                buttons=g.get("BTN_MEDIA"))
                    _UI["detail"] = gr.Markdown("", elem_id="rt-detail")
                with gr.Column(elem_classes=["panel"], elem_id="rt-time"):
                    _UI["extend"] = gr.Checkbox(value=True, label="終わりから延長する", elem_id="rt-extend")
                    _UI["t"] = gr.Slider(0.0, 10.0, value=10.0, step=round(1 / 24.0, 5), label="撮り直す位置（秒）",
                                         interactive=False, elem_id="rt-t")
                    _UI["pos"] = gr.Button("▶ 再生位置を使う", elem_id="rt-pos-btn")
                _UI["rm"] = gr.HTML(_refmod_html([]), elem_id="rt-refmods")
            with gr.Column(scale=1, elem_id="rt-right"):
                with gr.Column(elem_classes=["panel"], elem_id="rt-act"):
                    _UI["action"] = gr.Textbox(label="続きの挙動（動き・セリフ）", lines=5, elem_id="rt-action",
                                               placeholder="例: <Subject 2> laughs and says <d>[Japanese] …</d>（人物・場所・カメラは書かなくてよい）")
                    _UI["add"] = gr.Slider(4.0, 14.0, value=5.0, step=0.5, label="足す長さ（秒）", elem_id="rt-add")
                    _UI["seed"] = gr.Number(value=-1, precision=0, label="Seed（−1 で元＋1）", elem_id="rt-seed")
                    try:
                        _tc = list(g["turbo_choices"]())
                    except Exception:                             # noqa: BLE001
                        _tc = []
                    _UI["turbo"] = gr.Dropdown(choices=[("元と同じ", "")] + _tc, value="", label="⚡ Turbo LoRA",
                                               elem_id="rt-turbo", container=True, filterable=False)
                    _UI["steps"] = gr.Slider(0, 50, step=1, value=0, label="Steps（0 で自動）", elem_id="rt-steps")
                    _UI["inherit"] = gr.Checkbox(value=True, label="元の設定を引き継ぐ", elem_id="rt-inherit")
                    _UI["run"] = gr.Button("🎬 RETAKE", elem_id="rt-run-btn")
                with gr.Column(elem_classes=["panel"], elem_id="rt-status"):
                    _UI["msg"] = gr.Textbox(label="STATUS", lines=8, max_lines=int(g.get("STATUS_MAX_LINES", 200)),
                                            interactive=False, value="")
                with gr.Column(elem_classes=["panel"], elem_id="rt-out-box"):
                    _UI["out"] = gr.Video(label="RESULT", autoplay=True, height=box_h, interactive=False,
                                          elem_id="rt-out-video", buttons=g.get("BTN_MEDIA"))
                gr.Markdown("LIBRARY で動画を選んで「↪ RETAKE へ送る」か、SOURCE に動画を入れてください。", elem_id="rt-note")
        hi = g.get("help_icon")
        if hi is not None:
            try:
                hi(HELP_RT, anchor="#rt-action label > span:first-child", elem_id="rt-help")
            except Exception:                                     # noqa: BLE001
                pass


def _refmod_html(names):
    """0.5.0 元の動画の RefMod を CREATE のピッカーと同じタイル・番号で（押しても何も起きない表示だけ）"""
    import html as _html
    esc = _html.escape
    g = _g() if _ST.get("ctx") else {}
    T = _T if _ST.get("ctx") else (lambda s, **k: s.format(**k) if k else s)
    if not names:
        return (f'<div class="rmp-wrap"><div class="rmp-head"><span>{esc(T("RefMod"))}</span></div>'
                f'<div class="rmp-empty">{esc(T("元の動画は RefMod を使っていません"))}</div></div>')
    tiles = []
    for no, n in enumerate(names, 1):
        try:
            src = g["_refmod_thumb_src"](n) if "_refmod_thumb_src" in g else ""
        except Exception:                                         # noqa: BLE001
            src = ""
        leaf = g["_rmm_leaf"](n) if "_rmm_leaf" in g else n.split("/")[-1]
        pic = (f'<img src="{esc(src)}" alt="" loading="lazy" draggable="false">' if src
               else '<span class="rmp-noimg">🧬</span>')
        tiles.append(f'<div class="rmp-tile on" title="{esc(n)}">{pic}<span class="rmp-no">{no}</span>'
                     f'<span class="rmp-cap">{esc(leaf)}</span></div>')
    head = T("元の動画の RefMod（{v0} 件）", v0=len(names))
    return (f'<div class="rmp-wrap"><div class="rmp-head"><span>{esc(head)}</span></div>'
            f'<div class="rmp-grid">{"".join(tiles)}</div></div>')


def _load_source(path):
    """SOURCE に入れる動画 → (状態, 動画, 詳細, t のスライダー, メッセージ)"""
    gr = _ST["ctx"].gr
    g = _g()
    T = _T
    path = getattr(path, "name", path)
    if not path or not os.path.isfile(str(path)):
        return None, gr.update(), "", gr.update(), T("LIBRARY でファイルを選んでください"), gr.update()
    path = str(path)
    if g.get("is_still") and g["is_still"](path):
        return None, gr.update(), "", gr.update(), T("静止画は RETAKE できません（動画を選んでください）"), gr.update()
    try:
        w, h, n, fps, _a = g["_probe_video"](path)
    except Exception as e:                                        # noqa: BLE001
        return None, gr.update(), "", gr.update(), T("❌ 動画を読めませんでした: {v0}", v0=f"{e}"), gr.update()
    fpsx = float(g.get("FPS", 24))
    dur = round(int(n) / fpsx, 3)
    m = g["read_meta"](path) or {}
    lines = [f"### {os.path.basename(path)}", T("長さ {v0} 秒・{v1}×{v2}・{v3} コマ", v0=f"{dur:.2f}", v1=w, v2=h, v3=n)]
    if m.get("prompt"):
        rm = (m.get("refmods") or {}).get("names") or []
        bits = [str(m.get("mode") or "?"), f"{m.get('lora') or '?'} × {m.get('lora_strength', 1)}", f"Steps {m.get('steps', '?')}"]
        if rm:
            bits.append("RefMod " + " / ".join(rm))
        lines.append(T("元の設定: {v0}", v0=" ・ ".join(f"`{b}`" for b in bits)))
    else:
        lines.append(T("メタ（プロンプト）が無い動画です。「元の設定を引き継ぐ」は使えません"))
    mn = round(int(g.get("MOTION_CTX_FRAMES", 22)) / fpsx + 0.01, 2)
    rm_names = list((m.get("refmods") or {}).get("names") or []) if m.get("prompt") else []
    return (path, gr.update(value=path), "\n\n".join(lines),
            gr.update(minimum=mn, maximum=max(mn, dur), value=dur), "", _refmod_html(rm_names))


def wire(ctx, comps):
    gr = ctx.gr
    g = ctx.g
    if "run" not in _UI:
        return
    T = _T
    main_tabs = comps.get("main_tabs")
    load_out = [_UI["src"], _UI["src_video"], _UI["detail"], _UI["t"], _UI["msg"], _UI["rm"]]
    sel = comps.get("lib_sel_path")
    if "lib_btn" in _UI and sel is not None:
        ev = _UI["lib_btn"].click(fn=_load_source, inputs=[sel], outputs=load_out, queue=False, show_progress="hidden")
        if main_tabs is not None:
            ev.then(fn=lambda s: gr.update(selected="tab-retake") if s else gr.update(), inputs=[_UI["src"]],
                    outputs=[main_tabs], queue=False, show_progress="hidden")
    _UI["src_video"].upload(fn=_load_source, inputs=[_UI["src_video"]], outputs=load_out, queue=False, show_progress="hidden")
    _UI["extend"].change(fn=lambda e: gr.update(interactive=not e), inputs=[_UI["extend"]], outputs=[_UI["t"]],
                         queue=False, show_progress="hidden")
    # 再生位置: ブラウザの <video> の currentTime を読む（Python からは見えない）。読んだら延長を外す
    _UI["pos"].click(fn=None, inputs=None, outputs=[_UI["t"], _UI["extend"]],
                     js="() => { const v = document.querySelector('#rt-src-video video'); "
                        "return [v ? Math.round(v.currentTime * 24) / 24 : 0, false]; }")

    mode_c, steps_c = comps.get("mode"), comps.get("steps")
    extra_in = [c for c in (mode_c, steps_c) if c is not None]

    def _busy():
        return gr.update(value=T("⏳ 生成中…"), interactive=False)

    def _idle():
        return gr.update(value=T("🎬 RETAKE"), interactive=True)

    def _run(src, t, extend, action, add, seed, inherit, turbo, steps_ui, *extra):
        if not src or not os.path.isfile(str(src)):
            yield T("LIBRARY で動画を選んで「↪ RETAKE へ送る」か、SOURCE に動画を入れてください。"), gr.update()
            return
        if not str(action or "").strip():
            yield T("続きの挙動を書いてください"), gr.update()
            return
        busy = g.get("_BUSY")
        if busy is not None and busy.is_set():
            yield T("⛔ ほかの生成が終わるまでお待ちください"), gr.update()
            return
        m = g["read_meta"](src) or {}
        sd = int(seed if seed is not None else -1)
        if sd < 0:
            sd = int(m.get("seed", 0) or 0) + 1 if m.get("seed") is not None else int.from_bytes(os.urandom(4), "little")
        mode = extra[0] if (len(extra) > 0 and not inherit) else None
        steps = int(extra[1]) if (len(extra) > 1 and not inherit and extra[1]) else None
        if steps_ui and int(steps_ui) > 0:                        # 0.5.0 RETAKE で選んだ Steps が勝つ
            steps = int(steps_ui)
        if busy is not None:
            busy.set()
        last, res = "", None
        try:
            for st, r in retake(str(src), float(t or 0), float(add or 5), str(action), sd, mode=mode, steps=steps,
                                use_audio=True, extend=bool(extend), inherit=bool(inherit), turbo=(turbo or None)):
                last = st or last
                if r is not None:
                    res = r
                yield str(last), gr.update()
        finally:
            if busy is not None:
                busy.clear()
        yield str(last), (gr.update(value=res["joined"]) if res else gr.update())

    run_in = [_UI["src"], _UI["t"], _UI["extend"], _UI["action"], _UI["add"], _UI["seed"], _UI["inherit"],
              _UI["turbo"], _UI["steps"]] + extra_in
    # Turbo を選んだら Steps にその既定を入れる（「元と同じ」なら 0＝自動）。CREATE の Turbo と同じ動き
    _UI["turbo"].change(fn=lambda k: gr.update(value=int(_steps_for(k, None) or 0) if k else 0), inputs=[_UI["turbo"]],
                        outputs=[_UI["steps"]], queue=False, show_progress="hidden")
    _UI["run"].click(fn=_busy, outputs=[_UI["run"]], queue=False, show_progress="hidden").then(
        fn=_run, inputs=run_in, outputs=[_UI["msg"], _UI["out"]], show_progress="hidden",
        concurrency_id="generate", concurrency_limit=1).then(
        fn=_idle, outputs=[_UI["run"]], queue=False, show_progress="hidden")


if __name__ == "__main__":                                        # 構文の確認用
    print(NAME, VERSION, json.dumps(sorted(I18N))[:80])
