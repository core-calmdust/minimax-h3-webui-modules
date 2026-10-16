# Copyright (C) 2026 CALMDUST / AiHUB
# SPDX-License-Identifier: Apache-2.0
"""face_refiner — Face Refiner（顔の検出 → クリップ描き直し → 貼り戻し）。MiniMax H3 WebUI の拡張モジュール

WebUI 本体（セル3）がコミット固定で読み込み、`setup` を呼ぶ。本体の関数・状態は `ctx.g`（本体のグローバル）から借りる
（下の `_CORE_NAMES` を setup で取り込む。関数は呼ぶたびに本体から引き直すので、本体側の差し替えにも追従する）。
単体では動かない。WebUI ver1.7 #322 で本体（セル3）からこちらへ移した。UI（CREATE の Face Refiner 欄・UPSCALE の
「Face Refiner（顔）」）は本体に残り、本体は `ctx.provide` で登録したこのモジュールの関数を呼ぶ。

提供する関数（本体の同名のラッパーから呼ばれる）:
  face_refine_apply(frames, prompt, seed, cfg, restore_mode, prog=None) -> (frames, note)
  face_refine_still_img(pil_img, prompt, seed, cfg, restore_mode) -> (img, note)
  do_video_refine(path, strength, res, factor, prompt_txt="") -> (status, 動画) を逐次 yield

顔検出は OpenCV Zoo の YuNet（Apache-2.0、初回に取得）。クリップの描き直しで使う時刻の差し替え（`_sched`）は
diffusers の MiniMax H3 パイプライン（Apache-2.0, © HuggingFace）の SetTimestepsStep の手順に沿って組み直したもの。
"""
import datetime
import math
import os
import shutil
import subprocess
import time

import gradio as gr
import numpy as np
import torch
from PIL import Image

NAME = "face_refiner"
VERSION = "1.0.0"
API = 1
SLOTS = ()
# 処理中の文言（STATUS・ログ）。UI の部品の文言は本体の翻訳表にある（UI は本体のまま）
I18N = {
    "⚠️ 顔補正: 描き直しが破綻したため元のまま出力しました（差 {v0}／処理解像度を下げてみてください）": {"en": "⚠️ Face refine: the repaint broke down, so the output was left unchanged (difference {v0} / try a lower working resolution)", "zh": "⚠️ 面部修复：重绘结果异常，已按原样输出（差异 {v0}／请尝试降低处理分辨率）", "ko": "⚠️ 얼굴 보정: 다시 그린 결과가 깨져 원본 그대로 출력했습니다 (차이 {v0} / 처리 해상도를 낮춰 보세요)"},
    "顔サイズ連動の強さを計算できませんでした（一律で続けます）: {v0}": {"en": "Could not compute face-size-scaled strength (continuing at a uniform strength): {v0}", "zh": "无法计算随人脸大小的强度（以统一强度继续）：{v0}", "ko": "얼굴 크기 연동 강도를 계산하지 못했습니다(균일 강도로 계속): {v0}"},
    "顔補正に失敗（元のまま出力します）: {v0}": {"en": "Face refine failed (output unchanged): {v0}", "zh": "面部修复失败（按原样输出）：{v0}", "ko": "얼굴 보정 실패(원본 그대로 출력): {v0}"},
    "❌ 動画を読めませんでした: {v0}": {"en": "❌ Could not read the video: {v0}", "zh": "❌ 无法读取视频：{v0}", "ko": "❌ 동영상을 읽지 못했습니다: {v0}"},
    "🙂 {v0}/{v1} 塊  ⏱ {v2}s  残り およそ {v3}s": {"en": "🙂 chunk {v0}/{v1}  ⏱ {v2}s  about {v3}s left", "zh": "🙂 第 {v0}/{v1} 块  ⏱ {v2}s  约剩 {v3}s", "ko": "🙂 {v0}/{v1} 덩어리  ⏱ {v2}s  남은 시간 약 {v3}s"},
    "／顔が見えない {v0}f は貼っていません": {"en": " / skipped {v0} frames where the face was not visible", "zh": "／未贴合看不到人脸的 {v0} 帧", "ko": " / 얼굴이 보이지 않는 {v0}f는 적용하지 않았습니다"},
    "メタデータの書き込みに失敗: {v0}": {"en": "Could not write the metadata: {v0}", "zh": "元数据写入失败：{v0}", "ko": "메타데이터 쓰기 실패: {v0}"},
    "顔サイズ連動の強さ調整を見送りました（一律で続けます）: {v0}": {"en": "Face-size-scaled strength skipped (continuing at a uniform strength): {v0}", "zh": "已跳过随人脸大小调整强度（以统一强度继续）：{v0}", "ko": "얼굴 크기 연동 강도 조정을 건너뜁니다(균일 강도로 계속): {v0}"},
    "ℹ️ 顔補正: 顔が見つからないため補正なし": {"en": "ℹ️ Face refine: no face found, skipped", "zh": "ℹ️ 面部修复：未找到人脸，已跳过", "ko": "ℹ️ 얼굴 보정: 얼굴을 찾지 못해 건너뜀"},
    "✅ 完了 ⏱ {v0}s → {v1}": {"en": "✅ Done ⏱ {v0}s → {v1}", "zh": "✅ 完成 ⏱ {v0}s → {v1}", "ko": "✅ 완료 ⏱ {v0}s → {v1}"},
    "音声の乗せ替えに失敗（映像のみ）: {v0}": {"en": "Could not carry the audio over (video only): {v0}", "zh": "音频转移失败（仅视频）：{v0}", "ko": "오디오 이전 실패(영상만): {v0}"},
    "Face Refiner: 顔検出器 {v0}": {"en": "Face Refiner: face detector {v0}", "zh": "Face Refiner：人脸检测器 {v0}", "ko": "Face Refiner: 얼굴 검출기 {v0}"},
    "ℹ️ 顔補正: 顔が十分大きいため補正なし": {"en": "ℹ️ Face refine: face is already large, skipped", "zh": "ℹ️ 面部修复：人脸已足够大，已跳过", "ko": "ℹ️ 얼굴 보정: 얼굴이 충분히 커서 건너뜀"},
    "⚙️ 顔を探しています…": {"en": "⚙️ Looking for faces…", "zh": "⚙️ 正在寻找人脸…", "ko": "⚙️ 얼굴을 찾고 있습니다…"},
    "   強さ {v0} / 処理解像度 {v1}px / 範囲 ×{v2} / {v3} 塊に分けて処理": {"en": "   strength {v0} / working resolution {v1}px / coverage ×{v2} / processed in {v3} chunks", "zh": "   强度 {v0} / 处理分辨率 {v1}px / 范围 ×{v2} / 分 {v3} 块处理", "ko": "   강도 {v0} / 처리 해상도 {v1}px / 범위 ×{v2} / {v3}개 덩어리로 처리"},
    "（強さ {v0}〜{v1}: 顔の大きさに追従）": {"en": " (strength {v0}–{v1}, following face size)", "zh": "（强度 {v0}〜{v1}：跟随人脸大小）", "ko": " (강도 {v0}~{v1}: 얼굴 크기에 따라)"},
    "❌ これは静止画です。動画を指定してください": {"en": "❌ This is a still image. Please choose a video", "zh": "❌ 这是静态图片。请选择视频", "ko": "❌ 정지 이미지입니다. 동영상을 지정해 주세요"},
    "🙂 顔補正: 顔(高さ{v0}px)を{v1}pxで描き直しました": {"en": "🙂 Face refine: repainted face (height {v0}px) at {v1}px", "zh": "🙂 面部修复：将脸（高 {v0}px）以 {v1}px 重绘", "ko": "🙂 얼굴 보정: 얼굴(높이 {v0}px)을 {v1}px로 다시 그렸습니다"},
    "🙂 Face Refiner: {v0}×{v1} / {v2}f / {v3}fps": {"en": "🙂 Face Refiner: {v0}×{v1} / {v2}f / {v3}fps", "zh": "🙂 Face Refiner：{v0}×{v1} / {v2}f / {v3}fps", "ko": "🙂 Face Refiner: {v0}×{v1} / {v2}f / {v3}fps"},
    "⚠️ 顔補正を跳ばしました: {v0}": {"en": "⚠️ Face refine skipped: {v0}", "zh": "⚠️ 已跳过面部修复：{v0}", "ko": "⚠️ 얼굴 보정 건너뜀: {v0}"},
    "⚠️ 顔補正を使えません: {v0}": {"en": "⚠️ Face refine unavailable: {v0}", "zh": "⚠️ 无法使用面部修复：{v0}", "ko": "⚠️ 얼굴 보정을 사용할 수 없음: {v0}"},
    "（{v0}f と長いので {v1}px から下げました）": {"en": " (reduced from {v1}px because the clip is {v0} frames long)", "zh": "（片段长达 {v0} 帧，已从 {v1}px 下调）", "ko": " ({v0}f로 길어서 {v1}px에서 낮췄습니다)"},
    "Face Refiner を使えません: {v0}": {"en": "Face Refiner unavailable: {v0}", "zh": "无法使用 Face Refiner：{v0}", "ko": "Face Refiner 사용 불가: {v0}"},
    "⚠️ 顔補正に失敗したため元のまま出力しました": {"en": "⚠️ Face refine failed; output left unchanged", "zh": "⚠️ 面部修复失败，按原样输出", "ko": "⚠️ 얼굴 보정 실패, 원본 그대로 출력"},
    "（顔が大きいので倍率を {v0} → {v1} に下げました）": {"en": " (face is large, so the factor was lowered {v0} → {v1})", "zh": "（人脸较大，倍率已从 {v0} 降至 {v1}）", "ko": "(얼굴이 커서 배율을 {v0} → {v1} 로 낮췄습니다)"},
    "ℹ️ 顔補正: 顔(高さ{v0}px)×倍率{v1}={v2}px が処理解像度 {v3}px に収まらないため補正なし（顔が小さい場面向けの機能です。倍率を下げれば掛かります）": {"en": "ℹ️ Face refine: face ({v0}px) × factor {v1} = {v2}px does not fit the processing size {v3}px, so it was skipped (this feature is for small faces; lower the factor to apply it)", "zh": "ℹ️ 面部修正：人脸({v0}px)×倍率{v1}={v2}px 超出处理分辨率 {v3}px，已跳过（此功能面向小脸；降低倍率即可生效）", "ko": "ℹ️ 얼굴 보정: 얼굴({v0}px)×배율{v1}={v2}px 가 처리 해상도 {v3}px 에 들어가지 않아 건너뜀(작은 얼굴용 기능입니다. 배율을 낮추면 적용됩니다)"},
}
CSS = ""

_CTX = {"g": None}
_CORE_NAMES = ('T', 'log', 'ensure_mode_ui', 'read_meta', 'pipe_state_kept', 'apply_auto_shift', '_face_frames_np', '_UP_PROC', 'write_meta', 'short_video_allowed', 'kf_latent_count', 'kf_lat_to_px', 'is_still', 'install_refiner_native', 'export_to_video', '_set_vae_tiling', '_read_video_rgb', '_probe_video', '_h3_img2img_window', '_ffmpeg_exe', '_extract_video', 'T2I_MODE', 'SAVE_TO_DRIVE', 'OUT_DIR', 'FPS', 'CACHE_DIR')


# 本体から取り込む名前（setup で中身が入る。ここは静的検査と読みやすさのための置き場）
T = log = ensure_mode_ui = read_meta = pipe_state_kept = apply_auto_shift = _face_frames_np = None
_UP_PROC = write_meta = short_video_allowed = kf_latent_count = kf_lat_to_px = is_still = install_refiner_native = None
export_to_video = _set_vae_tiling = _read_video_rgb = _probe_video = _h3_img2img_window = _ffmpeg_exe = None
_extract_video = T2I_MODE = SAVE_TO_DRIVE = OUT_DIR = FPS = CACHE_DIR = None


def _pipe():
    """本体のパイプライン（エンジン切替で差し替わるので、使うたびに引く）"""
    return _CTX["g"]["pipe"]


def _bind_core(g):
    """本体の名前をこのモジュールに取り込む。関数は呼ぶたびに本体から引き直す包みにする"""
    import types as _types
    mod = globals()

    def _dyn(n):
        def call(*a, **k):
            return g[n](*a, **k)
        call.__name__ = n
        return call
    for n in _CORE_NAMES:
        v = g[n]
        if callable(v) and isinstance(v, (_types.FunctionType, _types.BuiltinFunctionType)):
            mod[n] = _dyn(n)
        else:
            mod[n] = v


def setup(ctx):
    global YUNET_DIR
    _CTX["g"] = ctx.g
    _bind_core(ctx.g)
    YUNET_DIR = f"{ctx.g['CACHE_DIR']}/models"
    ctx.provide("face_refine_apply", face_refine_apply)
    ctx.provide("face_refine_still_img", face_refine_still_img)
    ctx.provide("do_video_refine", do_video_refine)


def build_slot(ctx, slot):
    return None


def wire(ctx, comps):
    return None


# ============================================================
#  Face Refiner（顔の検出 → クリップ描き直し → 貼り戻し。セル21で検証）
# ============================================================
# 仕組み: YuNet（OpenCV）で顔を全フレーム追跡 → 顔高×factor の固定キャンバスで切り出し →
# res px へ拡大してクリップ全体を部分デノイズ（σ階段方式・上の img2img と同じ）→
# 色合わせ＋コサインフェザー矩形で元位置へ貼り戻す。音声・尺は変えない。
# 実測（セル21・124f/顔高9%/384px）: 追跡17.7s + 描き直し8.8s、
# 鮮鋭度×1.16 / 同一性27.3dB / ちらつき×1.01。
FACE_REFINE_STEPS = 3        # 描き直しの forward 数の下限（cell16/21 の判断に合わせる）


def _face_steps(strength):
    """強さに応じた forward 数。

    ⚠️ 強さを上げたまま刻みが少ないと、1ステップの跳びが大きくなって
       フレームごとの描き直しがばらけ、**ちらつきとして見える**
       （0.45 は平気でも 0.55 で出る、という実機の報告）。
       強くするぶんだけ刻みを増やして、跳びの大きさを揃える。
    """
    s = float(strength)
    if s <= 0.45:
        return FACE_REFINE_STEPS
    if s <= 0.60:
        return FACE_REFINE_STEPS + 1
    return FACE_REFINE_STEPS + 2
# 🔴 YuNet のスコアしきい値（2026-09-21 / YOLO 時代の 0.25 から引き上げ）。
#    YuNet のスコアは YOLO より高めに出るので、0.25 だと背景の誤検出が軌跡に混ざる。
#    配布元の既定 0.9 は取りこぼしが多く、0.6 前後が「拾い・誤検出」の釣り合い（アニメ顔は下げる余地あり）
FACE_REFINE_CONF = 0.6       # 顔検出（YuNet）のスコアしきい値 … **軌跡を始める**のに要る確からしさ
# 🔴 軌跡を**続ける**ときの下限（2026-09-25 / 実機 ③ アニメの横顔で発覚）。YuNet は正面 0.75〜0.9 でも
#    横顔になると 0.3〜0.55 まで落ちる（アニメの横顔はとくに）。0.6 一本だと振り向いた時点で軌跡が切れ、
#    「顔が見つからない」になる。始まりは 0.6 で厳しく、直前の位置の近く（`_face_pick_track` の距離・大きさの
#    条件）なら 0.3 まで拾って続ける。離れた場所の低スコアは軌跡を始められないので誤検出は増えない
FACE_REFINE_CONF_LOW = 0.3
FACE_REFINE_FEATHER = 0.12   # フェザー幅（キャンバス比）
FACE_REFINE_SKIP_H = 0.45    # 顔がこれ以上大きい（画面高比）なら補正しない
# 🔴 窓が処理解像度に収まらないときも補正しない（2026-09-25 / 実機 ③ アニメ 295px 顔で発覚）。
#    窓 = 顔高 × 倍率 だが上限は処理解像度 R（124f では 448px に自動で下がる）。顔 295px × 3 = 885px が
#    448px に切り詰められると、①窓が顔ぎりぎりになりフェザー（12%）が髪・耳を横切って**二重の縁**が出る、
#    ②拡大が 1:1 なので細部は足されず、描き直しで**線がなまる**だけになる。
#    ⇒ 窓の要求が R をこの倍率より超えるなら「顔は既に十分な画素」とみなして跳ばす（倍率を下げれば通る）
FACE_REFINE_WIN_OVER = 1.25
# 収まらないときは**まず倍率を自動で下げる**（2026-09-25 / 利用者「倍率設定がないので大きめだとかかりません」）。
# 下限 1.5 まで下げても収まらないときだけ跳ばす。下げたことは STATUS に出す
FACE_REFINE_FACTOR_MIN = 1.5
# 顔サイズ連動の強さ（ComfyUI-H3-FaceRefine と同じ考え方・同じ既定値）。
# 引きから寄りへ動くショットを1回のパスで扱うため、**小さい顔ほど強く**描き直す。
FACE_REFINE_PX_SMALL = 30.0   # これ以下の顔の高さ(px) … 指定した強さそのまま
FACE_REFINE_PX_LARGE = 120.0  # これ以上の顔の高さ(px) … 下の割合まで弱める
FACE_REFINE_LARGE_SCALE = 0.35
FACE_REFINE_RATIO_MIN = 0.60  # スライダー値に対する下限・上限（振れ幅の頭打ち）
FACE_REFINE_RATIO_MAX = 1.50
FACE_REFINE_PX_MEDIAN = 5     # 顔の高さの中央値フィルタ幅。一瞬の誤検出を落とす
FACE_REFINE_PX_SMOOTH = 21    # 顔の高さのならし幅（フレーム）。検出のゆらぎを消す
FACE_REFINE_LAT_SMOOTH = 9    # 強さのならし幅（潜在フレーム）。段差＝ちらつきを消す
# 色合わせ係数のならし幅（フレーム）。⚠️ **1（＝ならさない）が正しい。**
# フレームごとに合わせると、貼り付けた部分の平均・分散は毎フレーム「元の映像」に
# 一致する。元の映像は滑らかなので、これ自体がちらつき止めになっている。
# ならすとその保証が消えて、かえって揺れが通る（検証で確認）。
FACE_REFINE_COLOR_SMOOTH = 1
# 描き直しが壊れていないかの判定。32×32 のグレースケールで元と比べた平均差が
# これを超えたら「破綻」とみなして貼らない。実フレームでの実測値:
#   軽い描き直し 0.5 / 強い描き直し 2.3 / かなり別人 14.9 ‖ 格子模様 42.7 / 真っ黒 99.3
FACE_REFINE_SANE_MAE = 30.0
# 1回の描き直しに渡せる画素数の目安（処理解像度² × フレーム数）。
# ⚠️ これを超えると VAE のエンコードが破綻して**真っ黒／格子模様**になる。
#    実測: 384²×192f は正常、512²×192f は破綻（差 105 ＝ ほぼ真っ黒）。
#    フレーム数が多いほど処理解像度を自動で下げる（下げた分は STATUS に出す）。
FACE_REFINE_PIX_BUDGET = 384 * 384 * 192
FACE_REFINE_TRACK_GAP = 12    # 軌跡をつなぎ続けられる見失いの長さ（フレーム）
FACE_REFINE_LOST_GRACE = 3    # これ以内の見失いは埋める（貼り付けの点滅を防ぐ）
FACE_REFINE_ALPHA_SMOOTH = 9  # 貼ってよい度合いのならし幅（境目をなだらかに）


def _face_res_cap(res, n_frames):
    """フレーム数に応じた処理解像度の上限（32の倍数）。静止画は制限しない"""
    if int(n_frames) <= 1:
        return int(res)
    lim = int(math.sqrt(float(FACE_REFINE_PIX_BUDGET) / float(n_frames)))
    lim = max(256, (lim // 32) * 32)
    return min(int(res), lim)


def _win_odd(n, win):
    """長さ n に収まる奇数の窓幅。3 未満なら 0（＝ならさない）"""
    win = int(win)
    if win < 3 or n < 3:
        return 0
    win = min(win, n if n % 2 else n - 1)
    if win % 2 == 0:
        win -= 1
    return win if win >= 3 else 0


def _median1d(a, win):
    """中央値フィルタ。**平均より先に**掛けて、単発の誤検出（顔サイズの飛び）を消す"""
    a = np.asarray(a, dtype=np.float32)
    win = _win_odd(a.size, win)
    if not win:
        return a
    pad = win // 2
    p = np.concatenate([np.full(pad, a[0], np.float32), a,
                        np.full(pad, a[-1], np.float32)])
    return np.array([np.median(p[i:i + win]) for i in range(a.size)], dtype=np.float32)


def _smooth1d(a, win):
    """端を折り返さずに（縁の値で埋めて）移動平均する。長さは変わらない。

    ⚠️ np.convolve の 'same' は端をゼロで埋めるので、そのまま使うと
       先頭と末尾の値が落ち込む。強さのカーブでは端が弱くなって目立つ。
    """
    a = np.asarray(a, dtype=np.float32)
    win = _win_odd(a.size, win)
    if not win:
        return a
    pad = win // 2
    padded = np.concatenate([np.full(pad, a[0], np.float32), a,
                             np.full(pad, a[-1], np.float32)])
    return np.convolve(padded, np.ones(win, np.float32) / win, mode="valid")
_FACE_DET = {"model": None, "err": ""}

# 🔴 顔検出器は **YuNet（OpenCV 同梱 `cv2.FaceDetectorYN`、Apache-2.0）**（2026-09-21）。
#    以前は ultralytics（YOLOv8）＋ Bingsu/adetailer を初回に pip で入れていたが、
#    ultralytics は **AGPL-3.0** で、import するだけで WebUI 全体に及ぶと配布元が主張している
#    （`claude/license_notes.md` §9）。WebUI を Apache-2.0 で配るために外した。
#    YuNet は追加 pip なし・ONNX 約 230KB・CPU で 1 フレーム十数 ms。実写の顔向けで、
#    アニメ顔の検出率は YOLO より落ちる（足りなければ anime-face-detector / MIT を任意導入）。
#    ⚠️ ONNX は GitHub の opencv_zoo から落とし、CACHE_DIR に置く（Drive なら次回以降は無通信）。
#       2023mar が読めない古い OpenCV では 2022mar へ落とす。
YUNET_DIR = None            # setup で本体の CACHE_DIR/models に決める
#    ⚠️ opencv_zoo は Git LFS。`raw.githubusercontent.com` は 131 バイトのポインタを返すので使わない。
#       LFS の実体は `media.githubusercontent.com`（確認済み 232,589 バイト）。`github.com/…/raw/` も実体へ転送するが
#       環境によって 403 になるので 2 番手。
_YUNET_HOSTS = ("https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/",
                "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/")
YUNET_MODELS = tuple((n, h + n) for n in ("face_detection_yunet_2023mar.onnx", "face_detection_yunet_2022mar.onnx")
                     for h in _YUNET_HOSTS)
YUNET_MAX_SIDE = 960          # 検出に渡す長辺の上限（これより大きい絵は縮めて検出し、箱を戻す）
YUNET_NMS = 0.3


def _yunet_fetch(name, url):
    """ONNX を CACHE_DIR/models に置く。既にあれば何もしない。パスを返す"""
    os.makedirs(YUNET_DIR, exist_ok=True)
    p = os.path.join(YUNET_DIR, name)
    if os.path.isfile(p) and os.path.getsize(p) > 10_000:
        return p
    import requests
    tmp = p + ".tmp"
    with requests.get(url, stream=True, timeout=(30, 300), allow_redirects=True) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                if chunk:
                    f.write(chunk)
    if os.path.getsize(tmp) < 10_000:               # LFS のポインタ等を掴んだ
        try: os.remove(tmp)
        except Exception: pass                                                # noqa: BLE001
        raise RuntimeError(f"YuNet の取得に失敗（サイズが小さすぎる）: {url}")
    os.replace(tmp, p)
    return p


class _YuNetDet:
    """cv2.FaceDetectorYN の薄い包み。`detect(rgb)` → [(x1, y1, x2, y2, conf), …]"""
    def __init__(self, cv2, path, conf):
        # ⚠️ 検出器には**低いほう**のしきい値を渡す。高い／低いの使い分けは `_face_pick_track` が行う
        self.cv2, self.path, self.conf = cv2, path, float(conf)
        self.size = None
        self.det = cv2.FaceDetectorYN.create(path, "", (320, 320), self.conf, YUNET_NMS, 5000)

    def detect(self, rgb):
        cv2 = self.cv2
        h, w = int(rgb.shape[0]), int(rgb.shape[1])
        s = min(1.0, float(YUNET_MAX_SIDE) / float(max(h, w)))
        img = rgb if s >= 1.0 else cv2.resize(rgb, (max(1, int(round(w * s))), max(1, int(round(h * s)))),
                                              interpolation=cv2.INTER_AREA)
        bgr = np.ascontiguousarray(img[:, :, ::-1])
        sz = (int(bgr.shape[1]), int(bgr.shape[0]))
        if sz != self.size:
            self.det.setInputSize(sz)
            self.size = sz
        _, faces = self.det.detect(bgr)
        out = []
        if faces is not None:
            for row in np.asarray(faces):
                x, y, bw, bh, sc = float(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[-1])
                if sc < self.conf or bw <= 0 or bh <= 0:
                    continue
                out.append((x / s, y / s, (x + bw) / s, (y + bh) / s, sc))
        return out


def _face_det():
    """YuNet 顔検出器（初回に取得・以後キャッシュ）。(model, エラー文) を返す"""
    if _FACE_DET["model"] is not None or _FACE_DET["err"]:
        return _FACE_DET["model"], _FACE_DET["err"]
    try:
        import cv2
        if not hasattr(cv2, "FaceDetectorYN"):
            raise RuntimeError(f"OpenCV {getattr(cv2, '__version__', '?')} に FaceDetectorYN がありません（4.5.4 以上が必要）")
        last = None
        for name, url in YUNET_MODELS:
            try:
                p = _yunet_fetch(name, url)
                _FACE_DET["model"] = _YuNetDet(cv2, p, min(FACE_REFINE_CONF, FACE_REFINE_CONF_LOW))
                log(T('Face Refiner: 顔検出器 {v0}', v0=name))
                break
            except Exception as e:                                            # noqa: BLE001
                last = e
        if _FACE_DET["model"] is None:
            raise last or RuntimeError("YuNet を用意できませんでした")
    except Exception as e:
        _FACE_DET["err"] = f"{type(e).__name__}: {str(e)[:120]}"
        log(T('Face Refiner を使えません: {v0}', v0=_FACE_DET["err"]))
    return _FACE_DET["model"], _FACE_DET["err"]




def _face_detect_all(det, arrs):
    """全フレームの検出結果 → [[(cx, cy, 高さ, 確信度), …], …]（全部の顔）"""
    out = []
    for a in arrs:
        fr = []
        for x1, y1, x2, y2, c in det.detect(np.asarray(a)):
            fr.append(((float(x1) + float(x2)) / 2.0,
                       (float(y1) + float(y2)) / 2.0,
                       float(y2) - float(y1), float(c)))
        out.append(fr)
    return out


def _face_pick_track(per_frame):
    """検出を人物ごとの軌跡にまとめ、**一番長く映っている人**を選ぶ。

    ⚠️ フレームごとに「一番確からしい顔」を選ぶと、通行人が写り込んだ瞬間に
       対象が入れ替わって窓が飛ぶ（＝顔以外を描き直してしまう）。
       近さと大きさで前後をつなぎ、続いている軌跡を採る。参照実装（ComfyUI 版）も
       「大半は連続性で決まる。埋め込みを見るのは候補が拮抗したときだけ」としている。

    Returns: {フレーム番号: (cx, cy, 高さ, 確信度)}（見つからなければ空）
    """
    tracks = []
    for i, dets in enumerate(per_frame):
        used = set()
        for tr in tracks:                      # 続いている軌跡を伸ばす
            if i - tr["last"] > FACE_REFINE_TRACK_GAP:
                continue
            px, py, ph, _ = tr["pts"][tr["last"]]
            best, bd = None, None
            for j, (cx, cy, h, _c) in enumerate(dets):
                if j in used:
                    continue
                d = math.hypot(cx - px, cy - py)
                if d > 1.2 * max(ph, h):       # 離れすぎ＝別人
                    continue
                if not (0.5 <= h / max(ph, 1e-6) <= 2.0):   # 大きさが違いすぎ＝別人
                    continue
                if bd is None or d < bd:
                    best, bd = j, d
            if best is not None:
                used.add(best)
                tr["pts"][i] = dets[best]
                tr["last"] = i
                tr["score"] += dets[best][3]
        for j, d in enumerate(dets):           # 余ったものは新しい軌跡（始めるのは確かな検出だけ）
            if j not in used and d[3] >= FACE_REFINE_CONF:
                tracks.append({"last": i, "pts": {i: d}, "score": d[3]})
    if not tracks:
        return {}
    return max(tracks, key=lambda t: t["score"])["pts"]      # 長く・確かに映った人


def _face_alpha(hit):
    """貼ってよい度合い（0〜1）。**顔を見失っている区間には貼らない**。

    ⚠️ 見失ったフレームを補間で埋めて描き直すと、振り向いて顔が見えていない
       ところに顔のようなものを貼ってしまう。短い見失いは埋め（点滅防止）、
       長い見失いはなだらかに 0 へ落とす。
    """
    a = np.asarray(hit, dtype=np.float32)
    g = int(FACE_REFINE_LOST_GRACE)
    if g > 0 and a.size > 2 * g:
        pad = np.pad(a, (g, g), mode="edge")
        a = (np.convolve(pad, np.ones(2 * g + 1, np.float32), "valid") > 0
             ).astype(np.float32)
    return np.clip(_smooth1d(a, FACE_REFINE_ALPHA_SMOOTH), 0.0, 1.0)


def _face_track(arrs, factor, res):
    """全フレームの顔を追跡して、切り出す窓（位置と大きさ）を返す。

    Returns:
        (dict(x0s, y0s, wins, alpha, face_h, face_px, lost) | None, 補正しない理由)
    """
    det, err = _face_det()
    if det is None:
        return None, T('⚠️ 顔補正を使えません: {v0}', v0=err)
    F = len(arrs)
    H, W = arrs[0].shape[:2]
    pts = _face_pick_track(_face_detect_all(det, arrs))
    cx = np.full(F, np.nan)
    cy = np.full(F, np.nan)
    fh = np.full(F, np.nan)
    for i, (px, py, h, _c) in pts.items():
        cx[i], cy[i], fh[i] = px, py, h
    hit = ~np.isnan(cx)
    min_hits = 1 if F == 1 else max(2, F // 5)
    if hit.sum() < min_hits:
        return None, T('ℹ️ 顔補正: 顔が見つからないため補正なし')
    idx = np.arange(F)
    for a in (cx, cy, fh):
        a[~hit] = np.interp(idx[~hit], idx[hit], a[hit])
    face_h = float(np.median(fh))
    if face_h >= FACE_REFINE_SKIP_H * H:
        return None, T('ℹ️ 顔補正: 顔が十分大きいため補正なし')
    factor_in = float(factor)
    _want = face_h * factor_in
    if _want > float(res) * FACE_REFINE_WIN_OVER:
        # 窓が処理解像度に収まらない → 倍率を「窓 ＝ 処理解像度」まで下げる（下限 1.5）。それでも無理なら跳ばす
        factor = max(FACE_REFINE_FACTOR_MIN, min(factor_in, float(res) / max(face_h, 1e-6)))
        if face_h * float(factor) > float(res) * FACE_REFINE_WIN_OVER:
            return None, T('ℹ️ 顔補正: 顔(高さ{v0}px)×倍率{v1}={v2}px が処理解像度 {v3}px に収まらないため補正なし（顔が小さい場面向けの機能です。倍率を下げれば掛かります）',
                           v0=f'{face_h:.0f}', v1=f'{factor_in:.1f}', v2=f'{_want:.0f}', v3=f'{int(res)}')
    # ⚠️ 切り出す窓は**フレームごとに顔の大きさへ合わせる**。
    #    全フレーム同じ大きさに固定すると、寄っていくショットで顔が窓からはみ出し、
    #    フェザーの境目が顔を横切って動く＝ちらつきになる（実機の動画で確認）。
    #    窓を追従させれば、描き直しに渡る顔の大きさが常に一定になり、
    #    足される細部の粒度もそろう（動画モデルにとっても扱いやすい）。
    #    ⚠️ 上限は**処理解像度**。これを超える窓にすると、描き直しに渡す前に
    #       縮小することになり、寄りの場面だけ顔がぼける（しかも寄るにつれて
    #       ぼけ方が変わるので、それ自体がちらつきに見える）。
    fh_s = _smooth1d(_median1d(fh, FACE_REFINE_PX_MEDIAN), FACE_REFINE_PX_SMOOTH)
    wins = np.clip(fh_s * float(factor), 64.0,
                   float(min(H, W, int(res)))).astype(np.float32)
    if F >= 7:
        try:
            from scipy.signal import savgol_filter
            win = min(31, F if F % 2 == 1 else F - 1)
            if win >= 5:
                cx = savgol_filter(cx, win, 2)
                cy = savgol_filter(cy, win, 2)
        except Exception:
            pass
    # ⚠️ **整数に丸めない。** 丸めると切り出し位置が「0,0,1,0,1,2…」と階段状に動く。
    #    小数のまま持ち、切り出しと貼り戻しをサブピクセル精度で行う。
    x0s = np.clip(cx - wins / 2.0, 0, np.maximum(0.0, W - wins)).astype(np.float32)
    y0s = np.clip(cy - wins / 2.0, 0, np.maximum(0.0, H - wins)).astype(np.float32)
    alpha = _face_alpha(hit)
    return dict(x0s=x0s, y0s=y0s, wins=wins, alpha=alpha, face_h=face_h,
                face_px=fh, lost=int((alpha < 0.5).sum()),
                factor_used=float(factor), factor_in=factor_in), ""


def _face_warp_in(arr, fx, fy, canvas, res):
    """(fx,fy) を左上とする canvas 角の正方形を res×res で取り出す（サブピクセル精度）。

    ⚠️ PIL の AFFINE 係数は **出力→入力** の写像。切り出しと拡大を1回の再標本化で
       やるので、整数クロップ＋resize の2段より滲みも少ない。
    """
    k = float(canvas) / float(res)
    return Image.fromarray(np.asarray(arr, dtype=np.uint8)).transform(
        (res, res), Image.AFFINE, (k, 0.0, float(fx), 0.0, k, float(fy)),
        resample=Image.BICUBIC)


def _face_warp_out(img, fx, fy, canvas, res, size, mode="RGB"):
    """res×res の画像を元のフレーム上の位置（size=(W,H)）へ戻す"""
    k = float(canvas) / float(res)
    inv = (1.0 / k, 0.0, -float(fx) / k, 0.0, 1.0 / k, -float(fy) / k)
    return img.transform(size, Image.AFFINE, inv, resample=Image.BICUBIC,
                         fillcolor=(0, 0, 0) if mode == "RGB" else 0.0)


def _face_strength_curve(face_px, strength, n_lat, num_frames):
    """フレームごとの顔の高さ(px) → 潜在フレームごとの強さ。

    小さい顔ほど強く、大きい顔は FACE_REFINE_LARGE_SCALE 倍まで線形に弱める。
    潜在フレーム k が受け持つ画素フレームの区間で平均を取る（写像は kf_lat_to_px）。

    ⚠️ **中央値がスライダーの値になるように正規化する。** 参照実装のように
       「小さい顔＝指定値」にすると、顔の大きさが変わらないショットでも
       スライダーの意味が変わってしまう。正規化しておけば、大きさが一定の
       ショットは従来どおりで、**変化するショットだけ**その中で強弱がつく。
    """
    px = _smooth1d(_median1d(face_px, FACE_REFINE_PX_MEDIAN), FACE_REFINE_PX_SMOOTH)
    lo, hi = FACE_REFINE_PX_SMALL, max(FACE_REFINE_PX_SMALL + 1.0, FACE_REFINE_PX_LARGE)
    a = np.clip((px - lo) / (hi - lo), 0.0, 1.0)
    w = 1.0 - a * (1.0 - FACE_REFINE_LARGE_SCALE)          # 相対的な重み
    med = float(np.median(w)) or 1.0
    # ⚠️ 中央値で割るだけだと、顔の大きさが偏ったショット（半分以上が寄り、など）で
    #    小さい側が跳ね上がって別人になる。**スライダー比で頭打ちにする**
    r = np.clip(w / med, FACE_REFINE_RATIO_MIN, FACE_REFINE_RATIO_MAX)
    per_px = np.clip(strength * r, 0.05, 0.8)
    centers = [kf_lat_to_px(k) for k in range(n_lat)]
    out = []
    for k in range(n_lat):
        lo_i = 0 if k == 0 else (centers[k - 1] + centers[k]) // 2
        hi_i = num_frames if k == n_lat - 1 else (centers[k] + centers[k + 1]) // 2
        lo_i = max(0, min(num_frames - 1, lo_i))
        hi_i = max(lo_i + 1, min(num_frames, hi_i))
        out.append(float(per_px[lo_i:hi_i].mean()))
    # ⚠️ 潜在フレーム間で強さが階段状に変わると、その境目が**ちらつき**に見える。
    #    最後にもう一度ならして、隣り合うフレームの差を小さくする（実機の指摘 2026-08-28）
    return [float(v) for v in _smooth1d(np.asarray(out, dtype=np.float32),
                                        FACE_REFINE_LAT_SMOOTH)]


def _h3_img2img_clip(crops_r, strength, steps, prompt, seed, shift_v, shift_a,
                     per_frame=None):
    """(F,R,R,3) uint8 のクリップを H3 で同解像度に描き直す（F は 17n+5）。

    _h3_img2img_window のクリップ版。フレーム一括でデノイズするため
    時間方向も同時に整い、ちらつきが増えない（セル21実測 ×1.01）。

    per_frame … 潜在フレームごとの強さ（長さ = 潜在枚数、各要素 ≤ strength）。
        与えると **フレームごとに描き直す量を変える**（ComfyUI 版の
        per-frame denoise 相当）。仕組みは ComfyUI の noise mask と同じで、
        1ステップごとに「元のまま進んだ軌道」へ引き戻す割合をフレーム別にする:

            x ← m·x + (1−m)·(t·z0 + (1−t)·ε)      m = s_k / s_max

        m=1 なら丸ごと描き直し、m=0 なら最後に元の潜在そのものへ戻る。
        ⚠️ 速度を間引く方式では m=0 のフレームが**ノイズのまま**残る（元に戻らない）。
           必ずクリーン側の軌道へ引き戻すこと。
    """
    import contextlib as _ctx
    from diffusers.modular_pipelines.minimax_h3 import before_denoise as _bd_fr
    from diffusers.modular_pipelines.minimax_h3 import denoise as _dn_fr
    from diffusers.modular_pipelines.minimax_h3.before_denoise import (
        patchify_video_latents as _patchify)

    F, R = crops_r.shape[0], crops_r.shape[1]

    def _ladder(shift, s0, n):
        b0 = s0 / (shift - (shift - 1.0) * s0)
        base = torch.linspace(b0, 0.0, n + 1, dtype=torch.float32)
        return shift * base / (1 + (shift - 1) * base)     # 終端は厳密に 0.0

    _vae = _pipe().vae
    _dev = next(_vae.parameters()).device
    _pm = torch.tensor(_pipe().pixel_mean).view(1, -1, 1, 1, 1)
    _ps = torch.tensor(_pipe().pixel_std).view(1, -1, 1, 1, 1)
    _lm = torch.tensor(_vae.config.latents_mean).view(1, -1, 1, 1, 1)
    _ls = torch.tensor(_vae.config.latents_std).view(1, -1, 1, 1, 1)
    x = torch.from_numpy(np.ascontiguousarray(crops_r)).to(_dev)
    x = x.float().div_(255.0).permute(3, 0, 1, 2)[None]
    x = (x - _pm.to(_dev)) / _ps.to(_dev)
    with torch.inference_mode():
        post = _vae.encode(x, return_dict=False)[0]
        z = post.sample(generator=torch.Generator().manual_seed(42))   # 本番の条件レシピ
    z0 = ((z.to(torch.float16).float().cpu()) - _lm) / _ls
    del x, z
    torch.cuda.empty_cache()
    # ⚠️ ここで**早めに**気づく。潜在が壊れていると出力は真っ黒／格子になるが、
    #    そのまま進むと 2 分かけて壊れた結果を作ることになる（実機で発生）。
    #    正規化後の潜在は標準偏差 1 前後になるはず
    _sd = float(z0.std())
    if not torch.isfinite(z0).all() or not (0.05 < _sd < 20.0):
        raise RuntimeError(
            f"VAE encode broke down at {R}px x {F}f (latent std={_sd:.3g})")

    s0 = float(strength)
    N = max(1, int(steps))
    torch.manual_seed(int(seed))
    torch.cuda.manual_seed_all(int(seed))
    _eps = torch.randn_like(z0)
    z_t = (1.0 - s0) * z0 + s0 * _eps

    n_lat = z0.shape[2]
    mask_f = None
    if per_frame is not None and len(per_frame) == n_lat:
        _m = np.clip(np.asarray(per_frame, dtype=np.float32) / max(s0, 1e-6), 0.0, 1.0)
        if float(_m.min()) < 0.999:            # 全部同じなら普通の一括で足りる
            mask_f = _m

    @_ctx.contextmanager
    def _frame_mask(sig_v):
        """フレームごとの描き直し量（ComfyUI の noise mask 相当）。

        1ステップ終わるごとに、行（＝潜在フレーム）別に
        「元のまま進んだ軌道」へ引き戻す。最後は t=1 なので m=0 の行は z0 に戻る。
        """
        if mask_f is None:
            yield
            return
        cls = _dn_fr.MiniMaxH3LoopSchedulerStep
        orig = cls.__call__
        cache = {}

        def wrapped(self, components, block_state, i, t):
            components, block_state = orig(self, components, block_state, i, t)
            try:
                n_cond = int(block_state.num_condition_video_rows or 0)
                lat = block_state.latents
                dev, dt = lat.device, lat.dtype
                if "z0" not in cache:
                    ps = tuple(components.patch_size)
                    z0p = _patchify(z0.to(dev, torch.float32), ps)
                    epp = _patchify(_eps.to(dev, torch.float32), ps)
                    rows = z0p.shape[0]
                    if rows != lat.shape[0] - n_cond or rows % (n_lat // ps[0]):
                        raise RuntimeError("row layout mismatch")
                    per = rows // (n_lat // ps[0])          # 1グループあたりの行数
                    mg = torch.from_numpy(mask_f).to(dev, torch.float32)
                    if ps[0] > 1:                            # 時間パッチはまとめて1値に
                        mg = mg[: (n_lat // ps[0]) * ps[0]].reshape(-1, ps[0]).mean(1)
                    cache.update(z0=z0p, eps=epp,
                                 m=mg.repeat_interleave(per).unsqueeze(1))
                sv = float(sig_v[i + 1]) if i + 1 < len(sig_v) else 0.0
                t_next = 1.0 - sv                            # H3 は t = 1−σ（t=1 が clean）
                keep = (t_next * cache["z0"] + (1.0 - t_next) * cache["eps"]).to(dt)
                m = cache["m"].to(dt)
                lat[n_cond:] = lat[n_cond:] * m + keep * (1.0 - m)
            except Exception as e:      # noqa: BLE001
                if "warned" not in cache:
                    cache["warned"] = True
                    log(T('顔サイズ連動の強さ調整を見送りました（一律で続けます）: {v0}',
                          v0=f'{type(e).__name__}: {e}'))
            return components, block_state

        cls.__call__ = wrapped
        try:
            yield
        finally:
            cls.__call__ = orig

    @_ctx.contextmanager
    def _sched(sig_v, sig_a):
        cls = _bd_fr.MiniMaxH3SetTimestepsStep
        orig = cls.__call__

        def wrapped(self, components, state):
            components, state = orig(self, components, state)
            dev_ = components._execution_device
            components.scheduler.set_timesteps(sigmas=sig_v, device=dev_)
            components.audio_scheduler.set_timesteps(sigmas=sig_a, device=dev_)
            ts = components.scheduler.timesteps
            ats = components.audio_scheduler.timesteps
            state.set("timesteps", ts)
            state.set("audio_timesteps", ats)
            state.set("row_timestep_plan", [
                tuple(t_.to(dev_) for t_ in cls.build_row_timesteps(
                    state.get("video_indices"), state.get("audio_indices"),
                    int(state.get("num_condition_video_rows") or 0),
                    int(state.get("num_condition_audio_rows") or 0),
                    state.get("text_indices").numel(),
                    float(tv), float(ta),
                    max(float(tv), components.keyframe_noise_aug), 1.0))
                for tv, ta in zip(ts, ats)])
            return components, state

        cls.__call__ = wrapped
        try:
            yield
        finally:
            cls.__call__ = orig

    # ⚠️ **VAE tiling を明示的に入れる。** ここは `_run_pipe` を通らず `pipe()` を
    #    直接呼ぶので、タイリングの状態が「直前の生成の残り」になってしまう。
    #    H3 は非タイルのデコードで**格子状のアーティファクト**が出る（処理解像度を
    #    上げたときに顔が格子模様に化ける、という実機の報告）。
    _set_vae_tiling(True)
    install_refiner_native()   # ⚠️ `_run_pipe` を通らないので明示的に（短いプロンプトの NaN 対策）
    _lv = _ladder(shift_v, s0, N)
    # ⚠️🔴 **`short_video_allowed()` を必ず掛ける**（2026-08-29 / 実機で踏んだ）。
    #    `pipe()` は 120〜360フレーム（5〜15秒）しか受け付けない。ここへ来るのは
    #    「顔の窓を切り出したクリップ」で、**元動画の長さとは無関係に短くなりうる**:
    #      ・短い動画（120フレーム未満）にそのまま顔補正をかけたとき
    #      ・長い動画を塊に割った**最後の余り**（例: 400f を 345+55 に割ると 56f）
    #    掛け忘れると
    #      ValueError: … must be between 120 and 360, got 56
    #    で落ちる。姉妹関数（`_h3_img2img_window`）には最初から掛かっていたので、
    #    こちらだけの掛け忘れだった。
    with _sched(_lv, _ladder(shift_a, 1.0, N)), _frame_mask(_lv), \
            torch.inference_mode(), short_video_allowed():
        res = _pipe()(prompt=str(prompt), width=R, height=R,
                   num_inference_steps=N + 1, num_frames=F, latents=z_t)
    out = _face_frames_np(_extract_video(res))
    return np.stack(out)


def _face_sane(org_seq, ref_seq):
    """描き直しが壊れていないかを見る。壊れていたら False（元のまま出す）。

    ⚠️ 格子模様や真っ黒など、たまに描き直しが破綻することがある。そのまま貼ると
       顔だけ別物になった動画が出てしまうので、**貼る前に**低解像度で見比べて、
       元とかけ離れていたら見送る。
    """
    n = len(ref_seq)
    idx = np.linspace(0, n - 1, min(9, n)).astype(int)
    diffs = []
    for i in idx:
        r = np.asarray(ref_seq[i], dtype=np.float32)
        if not np.isfinite(r).all():
            return False, 999.0
        a = np.asarray(Image.fromarray(np.asarray(org_seq[i], dtype=np.uint8))
                       .convert("L").resize((32, 32), Image.Resampling.BILINEAR),
                       dtype=np.float32)
        b = np.asarray(Image.fromarray(r.round().clip(0, 255).astype(np.uint8))
                       .convert("L").resize((32, 32), Image.Resampling.BILINEAR),
                       dtype=np.float32)
        diffs.append(float(np.abs(a - b).mean()))
    d = float(np.median(diffs))
    return d <= FACE_REFINE_SANE_MAE, d


def _face_feather(size, frac):
    r = np.ones(size, dtype=np.float32)
    m = max(2, int(size * frac))
    ramp = 0.5 - 0.5 * np.cos(np.linspace(0, math.pi, m))
    r[:m] = ramp
    r[-m:] = ramp[::-1]
    return r


def _face_color_params(org_seq, ref_seq):
    """色合わせの係数（チャンネルごとのゲインとオフセット）を求め、**時間方向にならす**。

    ⚠️ フレームごとに独立して平均・分散を合わせると、描き直し側の統計のわずかな
       揺れがそのまま明るさの揺れになり、**ちらつきとして見える**
       （実機の動画で、顔まわりの明るさに ±1.9 階調の高周波が出ていた）。
       係数をならせば、ゆっくりした色の差には追従したまま、フレーム単位の揺れが消える。
    """
    n = len(org_seq)
    gain = np.ones((n, 3), dtype=np.float32)
    bias = np.zeros((n, 3), dtype=np.float32)
    for i in range(n):
        o = np.asarray(org_seq[i], dtype=np.float32)
        r = np.asarray(ref_seq[i], dtype=np.float32)
        for ch in range(3):
            mo, so = o[..., ch].mean(), o[..., ch].std() + 1e-6
            mr, sr = r[..., ch].mean(), r[..., ch].std() + 1e-6
            g = float(np.clip(so / sr, 0.7, 1.4))
            gain[i, ch] = g
            bias[i, ch] = mo - g * mr
    if n >= 3:
        for ch in range(3):
            gain[:, ch] = _smooth1d(gain[:, ch], FACE_REFINE_COLOR_SMOOTH)
            bias[:, ch] = _smooth1d(bias[:, ch], FACE_REFINE_COLOR_SMOOTH)
    return gain, bias


def _face_stitch(dst_arr, ref_crop_r, fx, fy, canvas, mask_img, gain, bias,
                 alpha=1.0):
    """描き直したクロップを色合わせして、**サブピクセル精度で**元の位置へ戻す。

    ref_crop_r … res×res の描き直し / mask_img … res×res のフェザー（'F' モード）
    gain, bias … _face_color_params が返すそのフレームの係数（長さ3）
    alpha … このフレームで貼ってよい度合い（0 なら顔を見失っているので貼らない）
    """
    a = float(alpha)
    if a <= 0.01:
        return np.asarray(dst_arr, dtype=np.uint8)
    res = ref_crop_r.shape[0]
    H, W = dst_arr.shape[:2]
    ref_c = ref_crop_r.astype(np.float32) * np.asarray(gain, np.float32) \
        + np.asarray(bias, np.float32)
    ref_img = Image.fromarray(ref_c.round().clip(0, 255).astype(np.uint8))
    full = np.asarray(_face_warp_out(ref_img, fx, fy, canvas, res, (W, H)),
                      dtype=np.float32)
    m = np.asarray(_face_warp_out(mask_img, fx, fy, canvas, res, (W, H), mode="F"),
                   dtype=np.float32)[..., None]
    m = np.clip(m, 0.0, 1.0) * a
    out = dst_arr.astype(np.float32) * (1.0 - m) + full * m
    return out.round().clip(0, 255).astype(np.uint8)


def face_refine_apply(frames, prompt, seed, cfg, restore_mode, prog=None):
    """動画フレーム列に顔補正を当てる。(新しいフレームのリスト, ノート) を返す。

    顔が無い・小さすぎない・検出器が無い等は**元のまま返して生成を止めない**。
    ワークフローを t2va に切り替えて描き直すので、終わったら必ず元へ戻す。
    ⚠️ shift・VAE tiling も borrow して返す（pipe_state_kept）。返し忘れると
       **次の生成が壊れる**。
    """
    with pipe_state_kept():
        return _face_refine_apply_inner(frames, prompt, seed, cfg, restore_mode, prog)


def _face_refine_apply_inner(frames, prompt, seed, cfg, restore_mode, prog=None):
    try:
        arrs = _face_frames_np(frames)
        R_want = max(64, int(round(int(cfg["res"]) / 32)) * 32)
        R = _face_res_cap(R_want, len(arrs))     # 長いクリップでは自動で下げる
        tr, note = _face_track(arrs, cfg["factor"], R)
        if tr is None:
            return frames, note
        ok, msg = ensure_mode_ui("T2V")
        if not ok:
            return frames, T('⚠️ 顔補正を跳ばしました: {v0}', v0=msg)
        apply_auto_shift(int(globals().get("SHIFT_REF_STEPS", 8)))
        shift_v = float(_pipe().scheduler.shift)
        shift_a = float(_pipe().audio_scheduler.shift)
        wins, x0s, y0s = tr["wins"], tr["x0s"], tr["y0s"]
        # 切り出しは**サブピクセル精度**、窓の大きさはフレームごとに顔へ追従
        crops_r = np.stack([np.asarray(_face_warp_in(arrs[i], x0s[i], y0s[i],
                                                     wins[i], R))
                            for i in range(len(arrs))])
        # 顔の大きさに合わせて、フレームごとに描き直す量を変える
        # （引き→寄りのショットを1回のパスで扱うため）
        per_f = None
        if cfg.get("scale_by_size", True) and tr.get("face_px") is not None:
            try:
                per_f = _face_strength_curve(tr["face_px"], cfg["strength"],
                                             kf_latent_count(len(arrs)), len(arrs))
            except Exception as e:      # noqa: BLE001
                log(T('顔サイズ連動の強さを計算できませんでした（一律で続けます）: {v0}', v0=f'{e}'))
        # 階段は一番強いフレームに合わせ、残りはマスクで弱める（m = s_k / s_max）
        _s0 = max(per_f) if per_f else cfg["strength"]
        ref_r = _h3_img2img_clip(crops_r, _s0, _face_steps(_s0),
                                 prompt, seed, shift_v, shift_a, per_frame=per_f)
        _ok, _d = _face_sane(crops_r, ref_r)
        if not _ok:
            return frames, T('⚠️ 顔補正: 描き直しが破綻したため元のまま出力しました'
                             '（差 {v0}／処理解像度を下げてみてください）', v0=f'{_d:.0f}')
        _f1 = _face_feather(R, FACE_REFINE_FEATHER)
        mask_img = Image.fromarray(np.asarray(_f1[:, None] * _f1[None, :], dtype=np.float32))
        gain, bias = _face_color_params(crops_r, ref_r)
        _al = tr["alpha"]
        out = [Image.fromarray(_face_stitch(arrs[i], ref_r[i], x0s[i], y0s[i],
                                            wins[i], mask_img, gain[i], bias[i],
                                            alpha=float(_al[i])))
               for i in range(len(arrs))]
        _note = T('🙂 顔補正: 顔(高さ{v0}px)を{v1}pxで描き直しました',
                  v0=f"{tr['face_h']:.0f}", v1=f'{R}')
        if R < R_want:
            _note += T('（{v0}f と長いので {v1}px から下げました）',
                       v0=f'{len(arrs)}', v1=f'{R_want}')
        if abs(tr.get("factor_used", cfg["factor"]) - float(cfg["factor"])) > 0.01:
            _note += T('（顔が大きいので倍率を {v0} → {v1} に下げました）',
                       v0=f"{float(cfg['factor']):.1f}", v1=f"{tr['factor_used']:.1f}")
        if tr.get("lost"):
            _note += T('／顔が見えない {v0}f は貼っていません', v0=f"{tr['lost']}")
        if per_f is not None and (max(per_f) - min(per_f)) > 0.02:
            _note += T('（強さ {v0}〜{v1}: 顔の大きさに追従）',
                       v0=f'{min(per_f):.2f}', v1=f'{max(per_f):.2f}')
        return out, _note
    except Exception as e:
        log(T('顔補正に失敗（元のまま出力します）: {v0}', v0=f'{type(e).__name__}: {e}'))
        return frames, T('⚠️ 顔補正に失敗したため元のまま出力しました')
    finally:
        if restore_mode:
            try:
                ensure_mode_ui(restore_mode)
            except Exception:
                pass


def face_refine_still_img(pil_img, prompt, seed, cfg, restore_mode):
    """静止画（T2I / Ref2I）向けの顔補正。(PIL, ノート) を返す"""
    with pipe_state_kept():
        return _face_refine_still_inner(pil_img, prompt, seed, cfg, restore_mode)


def _face_refine_still_inner(pil_img, prompt, seed, cfg, restore_mode):
    try:
        arr = np.asarray(pil_img.convert("RGB"))
        R = max(64, int(round(int(cfg["res"]) / 32)) * 32)
        tr, note = _face_track([arr], cfg["factor"], R)
        if tr is None:
            return pil_img, note
        ok, msg = ensure_mode_ui(T2I_MODE)
        if not ok:
            return pil_img, T('⚠️ 顔補正を跳ばしました: {v0}', v0=msg)
        apply_auto_shift(int(globals().get("SHIFT_REF_STEPS", 8)))
        shift_v = float(_pipe().scheduler.shift)
        shift_a = float(_pipe().audio_scheduler.shift)
        cv, x0, y0 = float(tr["wins"][0]), float(tr["x0s"][0]), float(tr["y0s"][0])
        crop_r = np.asarray(_face_warp_in(arr, x0, y0, cv, R))
        ref = _h3_img2img_window(crop_r, cfg["strength"], _face_steps(cfg["strength"]),
                                 prompt, seed, shift_v, shift_a)
        _ok, _d = _face_sane([crop_r], [ref])
        if not _ok:
            return pil_img, T('⚠️ 顔補正: 描き直しが破綻したため元のまま出力しました'
                              '（差 {v0}／処理解像度を下げてみてください）', v0=f'{_d:.0f}')
        _f1 = _face_feather(R, FACE_REFINE_FEATHER)
        mask_img = Image.fromarray(np.asarray(_f1[:, None] * _f1[None, :], dtype=np.float32))
        g, b = _face_color_params([crop_r], [ref])
        out = _face_stitch(arr, ref, x0, y0, cv, mask_img, g[0], b[0],
                           alpha=float(tr["alpha"][0]))
        return Image.fromarray(out), T('🙂 顔補正: 顔(高さ{v0}px)を{v1}pxで描き直しました',
                                       v0=f"{tr['face_h']:.0f}", v1=f'{R}')
    except Exception as e:
        log(T('顔補正に失敗（元のまま出力します）: {v0}', v0=f'{type(e).__name__}: {e}'))
        return pil_img, T('⚠️ 顔補正に失敗したため元のまま出力しました')
    finally:
        if restore_mode:
            try:
                ensure_mode_ui(restore_mode)
            except Exception:
                pass


def _grid_up(n):
    """H3 が受け付けるフレーム数（17n+5）へ切り上げる"""
    n = int(n)
    if n <= 5:
        return 5
    return 5 + 17 * int(math.ceil((n - 5) / 17.0))


def _face_chunk_len(res):
    """一度に描き直すフレーム数。画素数の目安と H3 の上限（345f）に収める"""
    lim = min(345, max(5, int(FACE_REFINE_PIX_BUDGET / float(max(64, res) ** 2))))
    n = 5
    while 5 + 17 * ((n - 5) // 17 + 1) <= lim:
        n = 5 + 17 * ((n - 5) // 17 + 1)
    return n




def do_video_refine(path, strength, res, factor, prompt_txt=""):
    """出来上がった動画に顔補正だけを掛け直す。(status, 結果の動画) を逐次 yield。

    ⚠️ H3 はフレーム数が 17n+5 でないと受け付けないので、**塊に切って**渡し、
       足りない分は最後のフレームで埋めてから捨てる。塊の長さは画素数の目安
       （処理解像度² × フレーム数）に収める。
    """
    if not path or not os.path.isfile(path):
        yield (T('❌ 元動画がありません。ドロップするか CREATE / LIBRARY から送ってください'),
               gr.update())
        return
    if is_still(path):
        yield (T('❌ これは静止画です。動画を指定してください'), gr.update())
        return
    R = max(64, int(round(int(res) / 32)) * 32)
    cfg = {"strength": max(0.05, min(0.8, float(strength))), "res": R,
           "factor": max(1.5, min(5.0, float(factor)))}
    try:
        w, h, _n, fps, _has_a = _probe_video(path)
        fps = float(fps or FPS)
        frames = _read_video_rgb(path, w, h)
    except Exception as e:      # noqa: BLE001
        yield (T('❌ 動画を読めませんでした: {v0}', v0=f'{type(e).__name__}: {e}'), gr.update())
        return

    N = int(frames.shape[0])
    prompt = str(prompt_txt or "").strip()
    if not prompt:
        try:
            m = read_meta(path) or {}
            prompt = str(m.get("prompt", "")).strip()
        except Exception:
            prompt = ""
    if not prompt:
        prompt = ("a detailed human face, sharp coherent facial features, "
                  "natural skin texture, clear eyes")

    chunk = _face_chunk_len(R)
    n_chunk = int(math.ceil(N / float(chunk)))
    # ⚠️ **塊の長さを均す。** 素直に前から切ると最後が極端に短い余りになり
    #    （400f / 345 → 345 + 55）、その1塊だけ描き直しの質が落ちる。
    #    塊の数はそのままに、長さを等分に近づける（上限は超えない）。
    if n_chunk > 1:
        chunk = min(chunk, int(math.ceil(N / float(n_chunk))))
        n_chunk = int(math.ceil(N / float(chunk)))
    head = [T('🙂 Face Refiner: {v0}×{v1} / {v2}f / {v3}fps', v0=f'{w}', v1=f'{h}',
              v2=f'{N}', v3=f'{fps:.0f}'),
            T('   強さ {v0} / 処理解像度 {v1}px / 範囲 ×{v2} / {v3} 塊に分けて処理',
              v0=f"{cfg['strength']:.2f}", v1=f'{R}', v2=f"{cfg['factor']:g}",
              v3=f'{n_chunk}'), ""]
    yield ("\n".join(head + [T('⚙️ 顔を探しています…')]), gr.update())

    _UP_PROC["cancel"] = False
    out, notes = [], []
    t0 = time.time()
    for ci in range(n_chunk):
        if _UP_PROC.get("cancel"):
            yield ("\n".join(head + [T('⛔ 中断しました')]), gr.update())
            return
        seg = list(frames[ci * chunk:(ci + 1) * chunk])
        keep_n = len(seg)
        need = _grid_up(keep_n)
        if need > keep_n:                       # 足りない分は最後のフレームで埋める
            seg = seg + [seg[-1]] * (need - keep_n)
        try:
            done, note = face_refine_apply(seg, prompt, 123 + ci, cfg, None)
        except Exception as e:                  # noqa: BLE001
            log(T('顔補正に失敗（元のまま出力します）: {v0}', v0=f'{type(e).__name__}: {e}'))
            done, note = seg, T('⚠️ 顔補正に失敗したため元のまま出力しました')
        out.extend(list(done)[:keep_n])
        if note and note not in notes:
            notes.append(note)
        el = time.time() - t0
        left = el / max(1, ci + 1) * (n_chunk - ci - 1)
        yield ("\n".join(head + notes
                         + [T('🙂 {v0}/{v1} 塊  ⏱ {v2}s  残り およそ {v3}s',
                              v0=f'{ci + 1}', v1=f'{n_chunk}', v2=f'{el:.0f}',
                              v3=f'{left:.0f}')]), gr.update())

    pil = [f if isinstance(f, Image.Image) else Image.fromarray(np.asarray(f, np.uint8))
           for f in out]
    stamp = f"{datetime.datetime.now():%H%M%S}"
    dst = f"/content/minimax_h3_{stamp}_face.mp4"
    export_to_video(pil, dst, fps=int(round(fps)))
    # 音声は元のものをそのまま乗せ替える（顔補正は音に触らない）
    try:
        tmp = dst + ".mux.mp4"
        r = subprocess.run([_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", dst,
                            "-i", path, "-map", "0:v", "-map", "1:a?",
                            "-c:v", "copy", "-c:a", "aac", "-shortest", tmp],
                           capture_output=True)
        if r.returncode == 0 and os.path.isfile(tmp):
            os.replace(tmp, dst)
    except Exception as e:      # noqa: BLE001
        log(T('音声の乗せ替えに失敗（映像のみ）: {v0}', v0=f'{e}'))
    try:
        meta = read_meta(path) or {"app": "MiniMax H3 WebUI", "app_version": "1.6"}
        meta["face_refine"] = dict(cfg)
        meta["face_refine_source"] = os.path.basename(path)
        write_meta(dst, meta)
    except Exception as e:      # noqa: BLE001
        log(T('メタデータの書き込みに失敗: {v0}', v0=f'{e}'))
    if SAVE_TO_DRIVE:
        try:
            shutil.copy2(dst, os.path.join(OUT_DIR, os.path.basename(dst)))
        except Exception as e:      # noqa: BLE001
            log(T('Drive への保存に失敗: {v0}', v0=f'{e}'))
    yield ("\n".join(head + notes
                     + [T('✅ 完了 ⏱ {v0}s → {v1}', v0=f'{time.time() - t0:.0f}',
                          v1=f'{os.path.basename(dst)}')]), gr.update(value=dst))


