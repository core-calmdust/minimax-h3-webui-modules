# Copyright (C) 2026 CALMDUST / AiHUB
# SPDX-License-Identifier: Apache-2.0
"""ref_filters — LIBRARY の動画・静止画を「他の生成 AI に渡す参照」向けに加工してダウンロードする。MiniMax H3 WebUI の拡張モジュール

利用者の用途（2026-10-24）: この WebUI で作った動画を Seedance などに参照（プレビズ）として渡すとき、
そのままだと相手のフィルタに弾かれることがある。明暗の構図・形・前後関係だけを残した加工だと通りやすく、結果も良かった。
LIBRARY のプレビューの下のボタン 1 つで「加工 → そのままダウンロード」まで行う（UPSCALE などへ送らない）。

  ・Blocking … 灰色 3 階調のベタ塗り（黒 27・灰 130・白 237。利用者の見本 MAS_blocking.mp4 を測った値）。
               縁を残すぼかし → 2 つのしきい値で 3 段 → 形をなめらかに。しきい値は**動画全体で 1 回**決める（コマごとだとちらつく）
  ・Blocking（人物）… 利用者指定: 背景を取り除く: 背景の模様が邪魔になるので、人物だけを残す。人物の切り抜きは torchvision の
               DeepLabV3（mobilenet_v3_large、BSD-3。重みは PyTorch 公式から自動取得）の person、前後でならす。
               背景は灰 130 の一色、人物の輪郭に黒 27 の細い線（人物の灰と背景の灰が溶けないように）。しきい値は人物の中だけで決める
  ・線画     … XDoG（差分ガウスの輪郭）。鉛筆の線画風の白地に黒線
  ・深度マップ … Video Depth Anything **Small**（ByteDance、コード・重みとも Apache-2.0。Base／Large は CC-BY-NC なので使わない）。
               動画用の時間方向のつながりを持つモデルで、コマ間でちらつきにくい。手前ほど白
               コードは配布元の GitHub を**版固定**（コミット）で取り寄せて import する（写さない）。重みは HF から版固定で取る

本体（セル3）は LIBRARY のプレビュー箱で `module_slot("lib_actions")` を呼び、`modules_wire` に `lib_sel_path`（選んでいるファイル）を渡す。
加工結果は /content/ref_filters/ に書く（LIBRARY・RECENT には出ない）。動画の音声はそのまま付ける。
"""
import os
import shutil
import subprocess
import sys
import time
import urllib.request

import numpy as np

NAME = "ref_filters"
VERSION = "1.0.0"
API = 1
SLOTS = ("lib_actions",)

OUT_DIR = "/content/ref_filters"
BLOCK_LEVELS = (27, 130, 237)           # 見本（MAS_blocking.mp4）の 3 階調。色は無い（R=G=B）
BLOCK_Q = (0.40, 0.80)                  # しきい値＝全体の明るさの分位（暗い 40% → 黒、80% まで → 灰、残り → 白）
BLOCK_SMOOTH = 1 / 160                  # 形をなめらかにする強さ（画面の高さに対する割合）
BLOCK_EMA = 0.5                         # コマ間でならす割合（ちらつき止め。0 で無し）
BLOCK_WORK_H = 540                      # ぼかしはこの高さに縮めてかける（両側フィルタが重い。形の細かさは変わらない）
BG_LEVEL, BG_EDGE = 130, 27             # 背景なし: 背景の灰・輪郭の線
MASK_EMA = 0.6                          # 人物マスクを前のコマとならす割合
LINE_SIGMA = 1 / 768                    # XDoG のぼかし（画面の高さに対する割合。768p で 1.0px）
DEPTH_REPO = "DepthAnything/Video-Depth-Anything"
DEPTH_COMMIT = "4f5ae23172ba60fd7bc11ef671cca678842c7072"
DEPTH_HF = ("depth-anything/Video-Depth-Anything-Small", "256875362cff76724b920335dfb4b29dd611f66e",
            "video_depth_anything_vits.pth", "13379300b739e659f076a59d52e9801bd8d38c541a7e71f73bbca4dcfb013609")
DEPTH_INPUT = 518                       # 配布元の既定の入力の大きさ
DEPTH_CHUNK = 720                       # 一度に推定するコマ数（30 秒）。長い動画はこの単位で区切る（区切りごとに濃淡を正規化）
DEPTH_MAXSIDE = 960                     # 推定に渡すコマの長辺（メモリを抑える。出力は元の大きさに戻す）

MODES = ("block", "blockfg", "line", "depth")
LABELS = {"block": "⬇ Blocking", "blockfg": "⬇ Blocking（人物）", "line": "⬇ 線画", "depth": "⬇ 深度マップ"}
NAMES = {"block": "Blocking", "blockfg": "Blocking（人物）", "line": "線画", "depth": "深度マップ"}

I18N = {
    "⬇ Blocking": {"en": "⬇ Blocking", "zh": "⬇ Blocking", "ko": "⬇ Blocking"},
    "⬇ Blocking（人物）": {"en": "⬇ Blocking (person)", "zh": "⬇ Blocking（人物）", "ko": "⬇ Blocking(인물)"},
    "Blocking（人物）": {"en": "Blocking (person only)", "zh": "Blocking（仅人物）", "ko": "Blocking(인물만)"},
    "⬇ 線画": {"en": "⬇ Line art", "zh": "⬇ 线稿", "ko": "⬇ 선화"},
    "⬇ 深度マップ": {"en": "⬇ Depth map", "zh": "⬇ 深度图", "ko": "⬇ 깊이 맵"},
    "参照用に加工しています（{v0}）…": {"en": "Converting for reference ({v0})…", "zh": "正在加工为参考用（{v0}）…",
                                "ko": "참조용으로 가공하는 중({v0})…"},
    "深度マップは初回だけモデル（約 110MB）を取得します": {"en": "The depth map downloads its model (about 110 MB) the first time",
                                     "zh": "深度图首次会下载模型（约 110MB）", "ko": "깊이 맵은 처음 한 번만 모델(약 110MB)을 받습니다"},
    "参照用に加工しました（{v0}・{v1} 秒）: {v2}": {"en": "Converted for reference ({v0}, {v1} s): {v2}",
                                    "zh": "已加工为参考用（{v0}・{v1} 秒）：{v2}", "ko": "참조용으로 가공했습니다({v0}・{v1}초): {v2}"},
    "参照用の加工に失敗しました: {v0}": {"en": "Reference conversion failed: {v0}", "zh": "参考用加工失败：{v0}",
                             "ko": "참조용 가공에 실패했습니다: {v0}"},
    "LIBRARY でファイルを選んでください": {"en": "Select a file in LIBRARY", "zh": "请在 LIBRARY 中选择文件",
                              "ko": "LIBRARY에서 파일을 선택하세요"},
    "Blocking": {"en": "Blocking", "zh": "Blocking", "ko": "Blocking"},
    "線画": {"en": "line art", "zh": "线稿", "ko": "선화"},
    "深度マップ": {"en": "depth map", "zh": "深度图", "ko": "깊이 맵"},
    "深度マップのモデルを読み込めません: {v0}": {"en": "Cannot load the depth model: {v0}", "zh": "无法加载深度模型：{v0}",
                                  "ko": "깊이 모델을 불러올 수 없습니다: {v0}"},
}

# 基準: 同じ箱の「⤴ UPSCALE へ送る」（#lib-up-btn）。大きさ・色・字・字間・角丸・枠を同じにし、3 つを横に並べる
CSS = """
/* ---- 拡張モジュール ref_filters ---- */
#rf-row, #rf-row2 { gap: 6px !important; margin: 0 !important; padding: 0 !important; flex-wrap: nowrap !important; }
#rf-row > *, #rf-row2 > * { min-width: 0 !important; flex: 1 1 0 !important; }
#rf-block, #rf-blockfg, #rf-line, #rf-depth {
    width: 100% !important; height: 34px !important; margin-top: 8px !important; min-width: 0 !important;
    padding: 0 6px !important; white-space: nowrap !important; overflow: hidden !important; text-overflow: ellipsis !important;
    background: var(--h3-elev) !important; border: 1px solid var(--h3-border2) !important;
    border-radius: 6px !important; color: var(--h3-muted) !important;
    font-size: 11px !important; letter-spacing: 0.12em !important; font-weight: 400 !important;
}
#rf-block:hover:not(:disabled), #rf-blockfg:hover:not(:disabled), #rf-line:hover:not(:disabled), #rf-depth:hover:not(:disabled) {
    background: var(--h3-border) !important; border-color: var(--h3-border-hover) !important; color: var(--h3-text) !important;
}
#rf-block:disabled, #rf-blockfg:disabled, #rf-line:disabled, #rf-depth:disabled { opacity: 0.35 !important; cursor: not-allowed !important; }
/* 受け渡し用のファイル欄は見せない（JS がここからダウンロードを始める） */
#rf-file { display: none !important; }
#lib-preview-box:fullscreen #rf-row, #lib-preview-box:fullscreen #rf-row2 { display: none !important; }
"""

# 出力のファイルを受け取ったら、ブラウザのダウンロードを始める（ページは移らない）
DL_JS = """(f) => {
  try {
    const v = Array.isArray(f) ? f[0] : f;
    if (!v) return;
    const url = v.url || (v.path ? ('/gradio_api/file=' + v.path) : null);
    if (!url) return;
    const a = document.createElement('a');
    a.href = url; a.download = v.orig_name || (v.path || '').split('/').pop() || 'reference';
    document.body.appendChild(a); a.click(); a.remove();
  } catch (e) { console.warn('[ref_filters]', e); }
}"""

_ST = {"ctx": None, "ui": {}, "depth": None, "depth_err": "", "seg": None}


def _g():
    return _ST["ctx"].g


def _T(s, **kw):
    return _ST["ctx"].T(s, **kw)


# ------------------------------------------------------------------
#  1 コマの加工（RGB uint8 → 灰色 uint8）
# ------------------------------------------------------------------
def _block_pre(rgb):
    """しきい値をかける前の灰色（縁を残すぼかし）"""
    import cv2
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    h, w = g.shape
    if h > BLOCK_WORK_H:
        sm = cv2.resize(g, (max(1, int(round(w * BLOCK_WORK_H / h))), BLOCK_WORK_H), interpolation=cv2.INTER_AREA)
        sm = cv2.bilateralFilter(sm, 0, 30, max(1, int(round(BLOCK_WORK_H / 300))) * 2)
        return cv2.resize(sm, (w, h), interpolation=cv2.INTER_LINEAR).astype(np.float32)
    s = max(1, int(round(h / 300)))
    return cv2.bilateralFilter(g, 0, 30, s * 2).astype(np.float32)


def _person_mask(rgb):
    """人物らしさ 0〜1（torchvision DeepLabV3 mobilenet の person）"""
    import torch
    if _ST["seg"] is None:
        import torchvision
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        net = torchvision.models.segmentation.deeplabv3_mobilenet_v3_large(weights="DEFAULT").eval().to(dev)
        _ST["seg"] = (net, dev)
    net, dev = _ST["seg"]
    import torch.nn.functional as F
    h, w = rgb.shape[:2]
    sh = 384
    sw = max(8, int(round(sh * w / h / 8)) * 8)
    x = torch.from_numpy(rgb).to(dev).permute(2, 0, 1)[None].float() / 255.0
    x = F.interpolate(x, size=(sh, sw), mode="bilinear", align_corners=False)
    mean = torch.tensor([0.485, 0.456, 0.406], device=dev).view(1, 3, 1, 1)
    std = torch.tensor([0.229, 0.224, 0.225], device=dev).view(1, 3, 1, 1)
    with torch.inference_mode():
        p = net((x - mean) / std)["out"].softmax(1)[:, 15:16]
        p = F.interpolate(p, size=(h, w), mode="bilinear", align_corners=False)
    return p[0, 0].float().cpu().numpy()


def _apply_bg(q8, m):
    """3 階調の絵 q8 と人物らしさ m → 背景を灰一色に、人物の輪郭に黒の細線"""
    import cv2
    fg = (m > 0.5).astype(np.uint8)
    k = max(3, int(round(fg.shape[0] / 180)) * 2 + 1)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    fg = cv2.medianBlur(fg * 255, k) > 127
    out = np.where(fg, q8, np.uint8(BG_LEVEL)).astype(np.uint8)
    t = max(1, int(round(fg.shape[0] / 400)))
    edge = cv2.morphologyEx(fg.astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((2 * t + 1, 2 * t + 1), np.uint8)) > 0
    out[edge & ~fg] = BG_EDGE
    return out


def _block_quant(gf, t0, t1):
    import cv2
    q = np.where(gf < t0, 0, np.where(gf < t1, 1, 2)).astype(np.uint8)
    k = max(3, int(round(gf.shape[0] * BLOCK_SMOOTH)) * 2 + 1)
    q = cv2.medianBlur(q, min(k, 255 if k % 2 else 254))
    return np.asarray(BLOCK_LEVELS, np.uint8)[q]


def _line(rgb):
    """XDoG: 白地に黒線"""
    import cv2
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
    s = max(0.6, g.shape[0] * LINE_SIGMA)
    d = cv2.GaussianBlur(g, (0, 0), s) - 0.98 * cv2.GaussianBlur(g, (0, 0), s * 1.6)
    e = np.where(d >= 0.0, 1.0, 1.0 + np.tanh(40.0 * d))
    return (e * 255.0).clip(0, 255).astype(np.uint8)


# ------------------------------------------------------------------
#  読み書き
# ------------------------------------------------------------------
def _probe(path):
    import cv2
    cap = cv2.VideoCapture(path)
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 24.0) or 24.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return w, h, fps, n


def _frames(path):
    import cv2
    cap = cv2.VideoCapture(path)
    try:
        while True:
            ok, f = cap.read()
            if not ok:
                break
            yield cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
    finally:
        cap.release()


class _Writer:
    """灰色のコマを ffmpeg に流して mp4 にする。元の動画の音声はそのまま付ける"""

    def __init__(self, src, out, w, h, fps):
        ff = _g()["_ffmpeg_exe"]()
        cmd = [ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{w}x{h}", "-r", f"{fps}",
               "-i", "-", "-i", src, "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
               "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", out]
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    def put(self, g8):
        self.p.stdin.write(np.ascontiguousarray(g8, np.uint8).tobytes())

    def close(self):
        self.p.stdin.close()
        err = self.p.stderr.read().decode("utf-8", "replace")
        if self.p.wait() != 0:
            raise RuntimeError(f"ffmpeg: {err[-300:]}")


# ------------------------------------------------------------------
#  深度（Video Depth Anything Small）
# ------------------------------------------------------------------
def _depth_model():
    if _ST["depth"] is not None:
        return _ST["depth"]
    import hashlib
    import tarfile
    import torch
    g = _g()
    base = os.path.join(g.get("CACHE_DIR", "/content"), "models", f"vda_{DEPTH_COMMIT[:7]}")
    src = os.path.join(base, "src")
    if not os.path.isdir(os.path.join(src, "video_depth_anything")):
        os.makedirs(base, exist_ok=True)
        tgz = os.path.join(base, "src.tar.gz")
        urllib.request.urlretrieve(f"https://codeload.github.com/{DEPTH_REPO}/tar.gz/{DEPTH_COMMIT}", tgz)
        tmp = os.path.join(base, "_x")
        shutil.rmtree(tmp, ignore_errors=True)
        with tarfile.open(tgz) as tf:
            tf.extractall(tmp, filter="data")
        top = os.path.join(tmp, os.listdir(tmp)[0])
        shutil.rmtree(src, ignore_errors=True)
        os.replace(top, src)
        shutil.rmtree(tmp, ignore_errors=True)
        os.remove(tgz)
    repo, rev, fn, sha = DEPTH_HF
    wpath = os.path.join(base, fn)
    if not os.path.isfile(wpath):
        from huggingface_hub import hf_hub_download
        p = hf_hub_download(repo, fn, revision=rev)
        shutil.copy2(p, wpath + ".tmp")
        os.replace(wpath + ".tmp", wpath)
    h = hashlib.sha256()
    with open(wpath, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    if h.hexdigest() != sha:
        os.remove(wpath)
        raise RuntimeError("重みの sha256 が合いません（取り直してください）")
    # ⚠️ 配布元は `from utils.util import …` と書く。ほかの `utils` と混ざらないよう、読み込みの間だけ差し替える
    saved = {k: sys.modules.pop(k) for k in list(sys.modules) if k == "utils" or k.startswith("utils.")}
    sys.path.insert(0, src)
    try:
        from video_depth_anything.video_depth import VideoDepthAnything
    finally:
        sys.path.remove(src)
        for k in [k for k in list(sys.modules) if k == "utils" or k.startswith("utils.")]:
            sys.modules[f"_vda_{k}"] = sys.modules.pop(k)
        sys.modules.update(saved)
    m = VideoDepthAnything(encoder="vits", features=64, out_channels=[48, 96, 192, 384])
    m.load_state_dict(torch.load(wpath, map_location="cpu"), strict=True)
    m = m.to("cuda" if torch.cuda.is_available() else "cpu").eval()
    _ST["depth"] = m
    return m


def _depth_chunk(m, frames, fps, out_hw):
    """RGB の並び → 灰色 uint8 の並び（手前ほど白）。区切りごとに 2〜98% で正規化"""
    import cv2
    import torch
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    h0, w0 = frames[0].shape[:2]
    sc = min(1.0, DEPTH_MAXSIDE / max(h0, w0))
    if sc < 1.0:
        frames = [cv2.resize(f, (int(round(w0 * sc)), int(round(h0 * sc))), interpolation=cv2.INTER_AREA) for f in frames]
    d, _ = m.infer_video_depth(np.stack(frames), fps, input_size=DEPTH_INPUT, device=dev, fp32=False)
    d = np.asarray(d, np.float32)
    lo, hi = np.percentile(d, 2), np.percentile(d, 98)
    v = ((d - lo) / max(hi - lo, 1e-6)).clip(0, 1)
    H, W = out_hw
    out = [cv2.resize((x * 255.0).astype(np.uint8), (W, H), interpolation=cv2.INTER_LINEAR) for x in v]
    if dev == "cuda":
        torch.cuda.empty_cache()
    return out


# ------------------------------------------------------------------
#  1 本の加工
# ------------------------------------------------------------------
def convert(path, mode):
    """path（動画か静止画）→ 加工済みファイルのパス"""
    import cv2
    os.makedirs(OUT_DIR, exist_ok=True)
    stem = os.path.splitext(os.path.basename(path))[0]
    still = bool(_g()["is_still"](path))
    out = os.path.join(OUT_DIR, f"{stem}_{mode}{'.png' if still else '.mp4'}")
    if still:
        rgb = cv2.cvtColor(cv2.imread(path, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
        if mode in ("block", "blockfg"):
            gf = _block_pre(rgb)
            m = _person_mask(rgb) if mode == "blockfg" else None
            vals = gf[m > 0.5] if (m is not None and (m > 0.5).any()) else gf
            g8 = _block_quant(gf, *np.quantile(vals, BLOCK_Q))
            if m is not None:
                g8 = _apply_bg(g8, m)
        elif mode == "line":
            g8 = _line(rgb)
        else:
            g8 = _depth_chunk(_depth_model(), [rgb], 24.0, rgb.shape[:2])[0]   # 1 コマでも配布元が足りない分を複製して埋める
        cv2.imwrite(out, g8)
        return out
    w, h, fps, n = _probe(path)
    w2, h2 = w - w % 2, h - h % 2                                 # yuv420p は偶数の大きさが要る
    wr = _Writer(path, out, w2, h2, fps)
    try:
        if mode in ("block", "blockfg"):
            fgm = mode == "blockfg"
            # しきい値は動画全体から 1 回（24 コマを見る）。背景なしは人物の中だけで決める
            cap = cv2.VideoCapture(path)
            samp = []
            for i in np.linspace(0, max(0, n - 1), min(24, max(1, n))).astype(int):
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
                ok, f = cap.read()
                if ok:
                    rgb = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
                    gf = _block_pre(rgb)
                    if fgm:
                        mm = _person_mask(rgb) > 0.5
                        if mm.any():
                            samp.append(gf[mm][::16])
                    else:
                        samp.append(gf[::4, ::4].ravel())
            cap.release()
            t0, t1 = np.quantile(np.concatenate(samp), BLOCK_Q) if samp else (85.0, 170.0)
            prev, pm = None, None
            for rgb in _frames(path):
                gf = _block_pre(rgb)
                if prev is not None and BLOCK_EMA > 0:
                    gf = BLOCK_EMA * prev + (1 - BLOCK_EMA) * gf
                prev = gf
                q8 = _block_quant(gf, t0, t1)
                if fgm:
                    m = _person_mask(rgb)
                    pm = m if pm is None else MASK_EMA * pm + (1 - MASK_EMA) * m
                    q8 = _apply_bg(q8, pm)
                wr.put(q8[:h2, :w2])
        elif mode == "line":
            for rgb in _frames(path):
                wr.put(_line(rgb)[:h2, :w2])
        else:
            m = _depth_model()
            buf = []
            for rgb in _frames(path):
                buf.append(rgb)
                if len(buf) >= DEPTH_CHUNK:
                    for g8 in _depth_chunk(m, buf, fps, (h, w)):
                        wr.put(g8[:h2, :w2])
                    buf = []
            if buf:
                for g8 in _depth_chunk(m, buf, fps, (h, w)):
                    wr.put(g8[:h2, :w2])
    finally:
        wr.close()
    return out


# ------------------------------------------------------------------
#  本体との約束
# ------------------------------------------------------------------
def setup(ctx):
    _ST["ctx"] = ctx
    ctx.provide("ref_filter_convert", convert)


def build_slot(ctx, slot):
    gr = ctx.gr
    ui = _ST["ui"]
    if slot == "lib_actions":                                    # LIBRARY ▸ プレビュー箱（UPSCALE へ送る の下）
        for rid, keys in (("rf-row", ("block", "blockfg")), ("rf-row2", ("line", "depth"))):
            with gr.Row(elem_id=rid):
                for k in keys:
                    ui[k] = gr.Button(LABELS[k], interactive=False, elem_id=f"rf-{k}", min_width=0)
        ui["file"] = gr.File(value=None, interactive=False, elem_id="rf-file", show_label=False)


def _sel_ok(path):
    return bool(path) and os.path.isfile(str(path))


def wire(ctx, comps):
    gr = ctx.gr
    ui = _ST["ui"]
    sel = comps.get("lib_sel_path")
    if sel is None or "block" not in ui:
        return
    btns = [ui[k] for k in MODES]

    def _avail(path):
        ok = _sel_ok(path)
        return [gr.update(interactive=ok) for _ in btns]
    sel.change(fn=_avail, inputs=[sel], outputs=btns, queue=False, show_progress="hidden")

    def _make(mode):
        name = NAMES[mode]

        def _busy(path):
            if not _sel_ok(path):
                gr.Warning(_T("LIBRARY でファイルを選んでください"))
            else:
                gr.Info(_T("参照用に加工しています（{v0}）…", v0=_T(name))
                        + (("\n" + _T("深度マップは初回だけモデル（約 110MB）を取得します"))
                           if mode == "depth" and _ST["depth"] is None else ""))
            return [gr.update(interactive=False) for _ in btns]

        def _run(path):
            if not _sel_ok(path):
                return None
            t0 = time.time()
            try:
                out = convert(str(path), mode)
            except Exception as e:                                # noqa: BLE001
                msg = f"{type(e).__name__}: {str(e)[:200]}"
                ctx.log(_T("参照用の加工に失敗しました: {v0}", v0=msg))
                gr.Warning(_T("参照用の加工に失敗しました: {v0}", v0=msg))
                return None
            ctx.log(_T("参照用に加工しました（{v0}・{v1} 秒）: {v2}", v0=_T(name), v1=f"{time.time() - t0:.1f}", v2=out))
            return out

        def _idle(path):
            return _avail(path)
        return _busy, _run, _idle

    for mode, b in zip(MODES, btns):
        _busy, _run, _idle = _make(mode)
        b.click(fn=_busy, inputs=[sel], outputs=btns, queue=False, show_progress="hidden").then(
            fn=_run, inputs=[sel], outputs=[ui["file"]], show_progress="hidden").then(
            fn=None, inputs=[ui["file"]], outputs=None, js=DL_JS).then(
            fn=_idle, inputs=[sel], outputs=btns, queue=False, show_progress="hidden")
