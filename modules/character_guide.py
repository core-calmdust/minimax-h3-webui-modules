# Copyright (C) 2026 CALMDUST / AiHUB
# SPDX-License-Identifier: Apache-2.0
"""character_guide — 長尺（Motion Context）で顔と画づくりを保つ。MiniMax H3 WebUI の拡張モジュール

WebUI ver1.7 の計測（セル168〜173、HANDOFF 0-AG #373〜#387）で決めた組み合わせ:
  ① **自己参照**（T2V の長尺のみ）: 1 本目から顔のよいコマを選び、2 本目以降を Ref2VA にしてそのコマを <Picture 1> として渡す。
     50 秒・6 本で顔の似かた（SFace cos）が 0.56→0.28（別人化）から 0.57→0.45 に（同一人物の目安 0.36 以上を保つ）。
  ② **明るさの掛け算合わせ**: 次へ渡す文脈（末尾 22 コマ）の明るさを 1 本目の文脈に掛け算で合わせる（倍率 0.8〜1.25、色は触らない）。
     長尺は回を重ねるほど明るく硬くなる（場面に依らない、1→6 本目で明るさ +20%）。足し引きで合わせると黒が浮いて霞むので掛け算。
  ③ **Detail & Contrast**（Fizgig H3 Tweaks＝MIT の考え方。コードは写さず自作）: 後半の歩だけ、最後の 10 ブロックで
     映像トークンへの更新を空間で帯域に分けて高域を足し引きする。既定 −0.2（尖りを抑える）。値は SYSTEM で選ぶ。
R2V の長尺は利用者の人物画像がもともと参照なので、①は使わず②③だけ掛ける。キーフレームを使う長尺では①を使わない。

本体（セル3）は `module_service("long_guide_session")` で `session(info)` を呼び、返った物の
plan / ctx_video / run_ctx / seg_done / pop_notes を各セグメントで呼ぶ（無ければ従来どおり）。
顔検出は OpenCV Zoo の YuNet（Apache-2.0、初回に取得して CACHE_DIR/models に置く）。
"""
import contextlib
import os

import numpy as np

NAME = "character_guide"
VERSION = "1.0.1"
API = 1
SLOTS = ("motion_group", "system_cards")

DETAIL_DEFAULT = -0.2
DETAIL_MIN, DETAIL_MAX, DETAIL_STEP = -0.5, 0.3, 0.005     # 1.0.1 利用者指定: スライダーで細かく（例 −0.185）
DETAIL_BLOCKS = 10           # 最後の何ブロックに掛けるか
GAIN_CLIP = (0.8, 1.25)
SELF_REF_PREFIX = ("The main character is the person shown in <Picture 1>; keep exactly the same face, "
                   "hairstyle and outfit as in <Picture 1>. ")
FACE_PNG = "cg_face.png"
FACE_SAMPLES = 24            # 1 本目から顔を探すコマ数
FACE_MIN_H = 0.08            # 顔の高さが画面のこれ未満なら使わない

_YUNET = (("face_detection_yunet_2023mar.onnx",
           "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"),
          ("face_detection_yunet_2023mar.onnx",
           "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"))

HELP_CB = ("**長尺で顔と画づくりを保ちます。**ON のとき 3 つを掛けます: ①T2V の長尺では 1 本目から顔のよいコマを選び、"
           "2 本目以降はそのコマを参照にして作ります（R2V に切り替わるので 1 本あたり約 1.5 倍の時間）。"
           "②次へ渡すコマの明るさを 1 本目に合わせます（回を重ねるほど明るく硬くなるのを止める）。"
           "③細部の尖りを抑えます（強さは SYSTEM ▸ Character Guide）。\n"
           "R2V の長尺は自分の人物画像が参照なので、②③だけ掛けます。キーフレームを使う長尺では①を使いません。"
           "選んだ顔のコマは STATUS に出ます")
HELP_SYS = ("Character Guide（CREATE ▸ Motion Context の下のスイッチ）で掛ける **Detail & Contrast** の強さです。"
            "マイナスほど細部の尖り・硬さを抑えます（−0.2 が計測で最良）。0 で掛けません。"
            "単発の生成には掛かりません")

I18N = {
    "Character Guide": {"en": "Character Guide", "zh": "Character Guide", "ko": "Character Guide"},
    "Character Guide（長尺の顔と画づくりを保つ）": {"en": "Character Guide (keep faces and look in long videos)",
                                          "zh": "Character Guide（长视频中保持人物与画面）",
                                          "ko": "Character Guide(긴 영상에서 얼굴과 화면 유지)"},
    "Detail & Contrast の強さ": {"en": "Detail & Contrast strength", "zh": "Detail & Contrast 强度", "ko": "Detail & Contrast 강도"},
    "−0.2（既定）": {"en": "−0.2 (default)", "zh": "−0.2（默认）", "ko": "−0.2(기본)"},
    "OFF（0）": {"en": "OFF (0)", "zh": "OFF（0）", "ko": "OFF(0)"},
    HELP_CB: {
        "en": "**Keeps faces and the look consistent in long videos.** When ON, three things are applied: ① In T2V long videos, a good face frame is picked from the 1st segment and used as the reference for the 2nd segment onward (this switches to R2V, so each segment takes about 1.5× longer). ② The brightness of the frames passed to the next segment is matched to the 1st (stops the drift toward brighter, harsher images). ③ Over-sharp detail is softened (strength in SYSTEM ▸ Character Guide).\nR2V long videos already use your own character image, so only ② and ③ are applied. ① is not used for long videos with keyframes. The chosen face frame is shown in STATUS",
        "zh": "**在长视频中保持人物脸部与画面风格。**开启后会做三件事：① T2V 长视频会从第 1 段中挑选脸部清晰的一帧，从第 2 段起以该帧为参考生成（切换为 R2V，每段耗时约 1.5 倍）。② 将传给下一段的画面亮度对齐到第 1 段（防止越来越亮、越来越硬）。③ 抑制细节过锐（强度在 SYSTEM ▸ Character Guide）。\nR2V 长视频本来就以你的人物图片为参考，因此只做 ② 和 ③。使用关键帧的长视频不使用 ①。所选的脸部帧会显示在 STATUS 中",
        "ko": "**긴 영상에서 얼굴과 화면 분위기를 유지합니다.** ON이면 세 가지를 적용합니다: ① T2V 긴 영상에서는 1번째 구간에서 얼굴이 잘 나온 프레임을 골라 2번째 구간부터 그 프레임을 참조로 만듭니다(R2V로 바뀌므로 구간당 약 1.5배 시간). ② 다음 구간에 넘기는 프레임의 밝기를 1번째에 맞춥니다(갈수록 밝고 딱딱해지는 것을 막음). ③ 디테일이 날카로워지는 것을 억제합니다(강도는 SYSTEM ▸ Character Guide).\nR2V 긴 영상은 원래 자신의 인물 이미지가 참조이므로 ②③만 적용합니다. 키프레임을 쓰는 긴 영상에는 ①을 쓰지 않습니다. 고른 얼굴 프레임은 STATUS에 표시됩니다"},
    HELP_SYS: {
        "en": "The strength of **Detail & Contrast** applied by Character Guide (the switch under CREATE ▸ Motion Context). More negative values soften over-sharp detail and harshness (−0.2 measured best). 0 disables it. Not applied to single generations",
        "zh": "Character Guide（CREATE ▸ Motion Context 下方的开关）所使用的 **Detail & Contrast** 强度。数值越负，越能抑制细节过锐和生硬感（实测 −0.2 最佳）。0 表示不使用。不作用于单段生成",
        "ko": "Character Guide(CREATE ▸ Motion Context 아래 스위치)가 적용하는 **Detail & Contrast** 강도입니다. 음수일수록 디테일의 날카로움과 딱딱함을 억제합니다(측정상 −0.2가 최적). 0이면 적용하지 않습니다. 단일 생성에는 적용되지 않습니다"},
    "🧑 Character Guide: 自己参照＋明るさ合わせ＋Detail {v0}": {
        "en": "🧑 Character Guide: self-reference + brightness matching + Detail {v0}",
        "zh": "🧑 Character Guide：自参考＋亮度对齐＋Detail {v0}", "ko": "🧑 Character Guide: 자기 참조＋밝기 맞춤＋Detail {v0}"},
    "🧑 Character Guide: 明るさ合わせ＋Detail {v0}（自己参照なし: {v1}）": {
        "en": "🧑 Character Guide: brightness matching + Detail {v0} (no self-reference: {v1})",
        "zh": "🧑 Character Guide：亮度对齐＋Detail {v0}（不使用自参考：{v1}）", "ko": "🧑 Character Guide: 밝기 맞춤＋Detail {v0}(자기 참조 없음: {v1})"},
    "R2V は自分の人物画像が参照": {"en": "R2V already uses your character image", "zh": "R2V 已以你的人物图片为参考", "ko": "R2V는 자신의 인물 이미지가 참조"},
    "キーフレームを使う長尺": {"en": "long video with keyframes", "zh": "使用关键帧的长视频", "ko": "키프레임을 쓰는 긴 영상"},
    "T2V 以外のモード": {"en": "mode other than T2V", "zh": "非 T2V 模式", "ko": "T2V 이외의 모드"},
    "  🧑 1 本目の {v0} 秒のコマを顔の参照にします（2 本目以降は R2V で作ります）": {
        "en": "  🧑 Using the frame at {v0} s of segment 1 as the face reference (segments 2+ are made with R2V)",
        "zh": "  🧑 将第 1 段 {v0} 秒处的帧作为脸部参考（第 2 段起用 R2V 生成）",
        "ko": "  🧑 1번째 구간 {v0}초 프레임을 얼굴 참조로 씁니다(2번째 구간부터 R2V로 생성)"},
    "  ⚠️ 1 本目に使える顔が見つからないので、自己参照なしで続けます": {
        "en": "  ⚠️ No usable face found in segment 1, continuing without self-reference",
        "zh": "  ⚠️ 第 1 段中找不到可用的脸，将不使用自参考继续", "ko": "  ⚠️ 1번째 구간에서 쓸 만한 얼굴을 찾지 못해 자기 참조 없이 계속합니다"},
    "  ⚠️ 顔を探せませんでした（自己参照なしで続けます）: {v0}": {
        "en": "  ⚠️ Could not search for a face (continuing without self-reference): {v0}",
        "zh": "  ⚠️ 无法查找脸部（将不使用自参考继续）：{v0}", "ko": "  ⚠️ 얼굴을 찾지 못했습니다(자기 참조 없이 계속): {v0}"},
    "  🧑 前回選んだ顔のコマを使います": {"en": "  🧑 Using the face frame chosen last time", "zh": "  🧑 使用上次选定的脸部帧",
                                "ko": "  🧑 지난번에 고른 얼굴 프레임을 씁니다"},
}

CSS = """
/* ---- 拡張モジュール character_guide ---- */
/* 基準: 同じ箱の Motion Context のチェック（#motion-ctx）。字・並び・余白を同じにする */
#cg-on, #cg-on label, #cg-on label span, #cg-on span {
    font-size: 12px !important; color: var(--h3-muted) !important;
    letter-spacing: 0.04em !important; font-weight: 400 !important;
}
#cg-on span { white-space: normal !important; line-height: 1.5 !important; }
#cg-on { padding-top: 8px !important; margin-top: 0 !important; }
/* 並びはドラフトモード（#t2i-fast）と同じ: 左にチェック → 文字 → ？（1.0.1 利用者指定） */
#cg-on label {
    display: flex !important; flex-direction: row !important; justify-content: flex-start !important;
    align-items: center !important; gap: 8px !important; white-space: nowrap !important;
}
#cg-on input[type="checkbox"] {
    accent-color: var(--h3-accent) !important; flex: 0 0 auto !important; margin: 0 !important;
}
/* 基準: SYSTEM の「R2V 長尺の Turbo」の箱（#rlt-card / #rlt-title / #rlt-dd） */
#cgd-card { margin-top: 16px !important; padding: 12px 14px !important; }
#cgd-title h4 {
    margin: 0 0 10px 0 !important; font-size: 13px !important;
    color: var(--h3-accent-2) !important;
    letter-spacing: 0.16em !important; font-weight: 700 !important;
}
/* スライダー: ラベルは #rlt-dd のラベル、数字の欄は値と同じ 13px・--h3-text、目盛りは #seg-len と同じ */
#cgd-sl { margin: 0 !important; }
#cgd-sl label, #cgd-sl label > span:first-child, #cgd-sl [data-testid="block-info"] {
    font-size: 12px !important; color: var(--h3-muted) !important;
    letter-spacing: 0.04em !important; font-weight: 400 !important;
}
#cgd-sl input[type="number"] { color: var(--h3-text) !important; font-size: 13px !important; letter-spacing: 0 !important; }
#cgd-sl .min-value, #cgd-sl .max-value,
#cgd-sl .min_value, #cgd-sl .max_value { color: var(--h3-faint) !important; font-size: 11px !important; }
"""

_ST = {"ctx": None, "ui": {}, "det": None, "det_err": ""}
_HK = {"step": 0, "n": 4, "k": 0.0, "hit": 0, "miss": 0}


def _g():
    return _ST["ctx"].g


def _T(s, **kw):
    return _ST["ctx"].T(s, **kw)


def _state():
    return _g()["_UI_STATE"]


def enabled():
    return bool(_state().get("cg_on", True))


def detail_k():
    try:
        v = float(_state().get("cg_detail", DETAIL_DEFAULT))
    except (TypeError, ValueError):
        v = DETAIL_DEFAULT
    return float(min(DETAIL_MAX, max(DETAIL_MIN, v)))


def _save(key, v):
    g = _g()
    try:
        _state()[key] = v
        _state()["version"] = g["UI_STATE_VERSION"]
        g["_write_ui_state"]()
    except Exception as e:                                       # noqa: BLE001
        _ST["ctx"].log(f"character_guide: {key} を保存できませんでした: {e}")


def _set_on(v):
    _save("cg_on", bool(v))
    return None


def _set_detail(v):
    try:
        _save("cg_detail", float(v))
    except (TypeError, ValueError):
        pass
    return None


# ------------------------------------------------------------------
#  顔を選ぶ（YuNet）
# ------------------------------------------------------------------
def _detector():
    if _ST["det"] is not None or _ST["det_err"]:
        return _ST["det"]
    try:
        import cv2
        d = os.path.join(str(_g()["CACHE_DIR"]), "models")
        os.makedirs(d, exist_ok=True)
        path = None
        for name, url in _YUNET:
            p = os.path.join(d, name)
            if os.path.isfile(p) and os.path.getsize(p) > 10_000:
                path = p
                break
            try:
                import requests
                r = requests.get(url, timeout=(30, 120), allow_redirects=True)
                r.raise_for_status()
                if len(r.content) > 10_000:                      # LFS のポインタ（131 バイト）を掴んでいない
                    with open(p + ".tmp", "wb") as f:
                        f.write(r.content)
                    os.replace(p + ".tmp", p)
                    path = p
                    break
            except Exception:                                    # noqa: BLE001
                continue
        if path is None:
            raise RuntimeError("YuNet を取得できません")
        _ST["det"] = cv2.FaceDetectorYN.create(path, "", (320, 320), 0.7, 0.3, 50)
    except Exception as e:                                       # noqa: BLE001
        _ST["det_err"] = f"{type(e).__name__}: {e}"
    return _ST["det"]


def _pick_face(frames):
    """コマの並びから顔の参照にするコマを選ぶ → (コマ番号, RGB) / None。
    点数 = 検出の確からしさ × 顔の大きさ（平方根）× 顔の鮮鋭度（中央値で割る）。顔が小さすぎるコマは使わない"""
    import cv2
    det = _detector()
    if det is None:
        raise RuntimeError(_ST["det_err"] or "YuNet が使えません")
    seq = list(frames)
    n = len(seq)
    if n == 0:
        return None
    cands = []
    for i in np.linspace(int(n * 0.1), n - 1, min(FACE_SAMPLES, n)).astype(int):
        f = seq[int(i)]
        rgb = np.asarray(f.convert("RGB")) if hasattr(f, "convert") else np.asarray(f)
        if rgb.dtype != np.uint8:
            rgb = np.clip(rgb * (255.0 if rgb.max() <= 1.0 else 1.0), 0, 255).astype(np.uint8)
        h, w = rgb.shape[:2]
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        det.setInputSize((w, h))
        _, faces = det.detect(bgr)
        if faces is None or len(faces) == 0:
            continue
        x, y, fw, fh, *_rest, conf = max(faces, key=lambda r: r[2] * r[3])
        if fh < FACE_MIN_H * h:
            continue
        x0, y0 = max(0, int(x)), max(0, int(y))
        crop = cv2.cvtColor(bgr[y0:y0 + int(fh), x0:x0 + int(fw)], cv2.COLOR_BGR2GRAY)
        sharp = float(cv2.Laplacian(crop, cv2.CV_32F).var()) if crop.size else 0.0
        cands.append([int(i), rgb, float(conf), float(fh) / h, sharp])
    if not cands:
        return None
    med = float(np.median([c[4] for c in cands])) or 1.0
    best = max(cands, key=lambda c: c[2] * (c[3] ** 0.5) * min(2.0, c[4] / med))
    return best[0], best[1]


# ------------------------------------------------------------------
#  Detail & Contrast（ブロックの更新の高域を足し引き）
# ------------------------------------------------------------------
def _blur(x, sigma=1.0):
    import torch
    import torch.nn.functional as F
    r = 2
    t = torch.arange(-r, r + 1, device=x.device, dtype=x.dtype)
    k = torch.exp(-(t ** 2) / (2 * sigma ** 2))
    k = k / k.sum()
    C = x.shape[1]
    x = F.pad(x, (r, r, r, r), mode="reflect")
    x = F.conv2d(x, k.view(1, 1, 1, -1).expand(C, 1, 1, -1).contiguous(), groups=C)
    return F.conv2d(x, k.view(1, 1, -1, 1).expand(C, 1, -1, 1).contiguous(), groups=C)


def _block_hook(_m, args, kwargs, out):
    import torch
    s = _HK
    if s["k"] == 0.0 or s["step"] < (s["n"] + 1) // 2:          # 後半の歩だけ
        return out
    try:
        hin = args[0] if args else kwargs.get("hidden_states")
        hout = out[0] if isinstance(out, (tuple, list)) else out
        if not torch.is_tensor(hin) or not torch.is_tensor(hout) or hin.shape != hout.shape or hin.ndim != 3:
            s["miss"] += 1
            return out
        geo = (_g().get("_VSA") or {}).get("geo") or {}
        T_, H_, W_ = [int(v) for v in geo.get("shape", (0, 0, 0))]
        st = int(sum(geo.get("prefix", ())))
        n = T_ * H_ * W_
        if n <= 0 or st + n > hout.shape[1] or H_ < 3 or W_ < 3:
            s["miss"] += 1
            return out
        B, _L, C = hout.shape
        d = (hout[:, st:st + n] - hin[:, st:st + n]).float()
        d = d.view(B, T_, H_, W_, C).permute(0, 1, 4, 2, 3).reshape(B * T_, C, H_, W_)
        hi = d - _blur(d)
        add = (s["k"] * hi).view(B, T_, C, H_, W_).permute(0, 1, 3, 4, 2).reshape(B, n, C).to(hout.dtype)
        hnew = hout.clone()
        hnew[:, st:st + n] += add
        s["hit"] += 1
        if isinstance(out, tuple):
            return (hnew,) + tuple(out[1:])
        if isinstance(out, list):
            return [hnew] + list(out[1:])
        return hnew
    except Exception:                                            # noqa: BLE001
        s["miss"] += 1
        return out


# ------------------------------------------------------------------
#  長尺の 1 回ぶん
# ------------------------------------------------------------------
class _Session:
    def __init__(self, info):
        g = _g()
        self.job = info.get("job")
        self.mode = info.get("mode")
        self.k_detail = detail_k()
        self.notes = []
        self.face = None
        self.ref_L = None
        why = ""
        if g["is_ref_mode"](self.mode):
            why = _T("R2V は自分の人物画像が参照")
        elif info.get("kf"):
            why = _T("キーフレームを使う長尺")
        elif self.mode != "T2V":
            why = _T("T2V 以外のモード")
        self.self_ref = not why
        dk = "OFF" if self.k_detail == 0 else f"{self.k_detail:+g}"
        if self.self_ref:
            self.notes.append(_T("🧑 Character Guide: 自己参照＋明るさ合わせ＋Detail {v0}", v0=dk))
            p = os.path.join(self.job, FACE_PNG) if self.job else None
            if p and os.path.isfile(p):
                self.face = p
                self.notes.append(_T("  🧑 前回選んだ顔のコマを使います"))
        else:
            self.notes.append(_T("🧑 Character Guide: 明るさ合わせ＋Detail {v0}（自己参照なし: {v1}）", v0=dk, v1=why))

    def pop_notes(self):
        n, self.notes = self.notes, []
        return n

    def plan(self, k, seg_mode, refs, prompt):
        """このセグメントのモード・参照・プロンプト。自己参照は 2 本目以降"""
        if not (self.self_ref and k >= 1 and self.face):
            return seg_mode, refs, prompt
        r = {kk: [] for kk in _g()["REF_KINDS"]}
        r["image"] = [self.face]
        return "Ref2VA", r, SELF_REF_PREFIX + str(prompt or "")

    def _lum(self, frames):
        import cv2
        return float(np.mean([cv2.cvtColor(np.asarray(f, np.uint8), cv2.COLOR_RGB2LAB)[..., 0].mean() for f in frames]))

    def ctx_video(self, k_prev, arr):
        """次へ渡す文脈の明るさを 1 本目の文脈に掛け算で合わせる → (新しい文脈, 潜在の控えを捨てるか)"""
        import cv2
        if arr is None:
            return arr, False
        if self.ref_L is None:
            a0 = arr if k_prev == 0 else _g()["_load_ctx"](self.job, 0, "video")
            if a0 is None:
                return arr, False
            self.ref_L = self._lum(a0)
        L = self._lum(arr)
        gain = float(np.clip(self.ref_L / max(L, 1e-3), *GAIN_CLIP))
        if abs(gain - 1.0) < 0.005:
            return arr, False
        out = []
        for f in arr:
            lab = cv2.cvtColor(np.asarray(f, np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
            lab[..., 0] *= gain
            out.append(cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB))
        return np.stack(out), True                               # 画素を書き換えたので潜在の控えは使わない

    @contextlib.contextmanager
    def run_ctx(self, k, n_steps):
        """このセグメントの生成のあいだだけ Detail のフックを付ける（エンジンが替わっても付け直す）"""
        if self.k_detail == 0:
            yield
            return
        tr = _g()["active_transformer"]()
        blocks = list(getattr(tr, "transformer_blocks", []) or [])
        _HK.update(step=-1, n=max(1, int(n_steps)), k=float(self.k_detail))

        def _pre(_m, _a, _kw):
            _HK["step"] += 1
        hs = [tr.register_forward_pre_hook(_pre, with_kwargs=True)]
        for b in blocks[-DETAIL_BLOCKS:]:
            hs.append(b.register_forward_hook(_block_hook, with_kwargs=True))
        try:
            yield
        finally:
            for h in hs:
                h.remove()
            _HK["k"] = 0.0

    def seg_done(self, k, frames):
        if not (self.self_ref and k == 0 and self.face is None):
            return
        try:
            got = _pick_face(frames)
        except Exception as e:                                   # noqa: BLE001
            self.self_ref = False
            self.notes.append(_T("  ⚠️ 顔を探せませんでした（自己参照なしで続けます）: {v0}", v0=f"{e}"[:160]))
            return
        if got is None:
            self.self_ref = False
            self.notes.append(_T("  ⚠️ 1 本目に使える顔が見つからないので、自己参照なしで続けます"))
            return
        i, rgb = got
        from PIL import Image
        p = os.path.join(self.job, FACE_PNG)
        Image.fromarray(rgb).save(p + ".tmp.png")
        os.replace(p + ".tmp.png", p)
        self.face = p
        fps = float(_g().get("FPS", 24) or 24)
        self.notes.append(_T("  🧑 1 本目の {v0} 秒のコマを顔の参照にします（2 本目以降は R2V で作ります）", v0=f"{i / fps:.1f}"))


def session(info):
    """本体の長尺が始まるときに呼ぶ。OFF なら None"""
    if not enabled() or not info.get("mc"):
        return None
    return _Session(info)


# ------------------------------------------------------------------
#  本体との約束
# ------------------------------------------------------------------
def setup(ctx):
    _ST["ctx"] = ctx
    ctx.provide("long_guide_session", session)


def build_slot(ctx, slot):
    gr = ctx.gr
    g = ctx.g
    ui = _ST["ui"]
    if slot == "motion_group":                                   # CREATE ▸ Motion Context の箱（Segment Length の下）
        ui["cb"] = gr.Checkbox(value=enabled() and bool(g["motion_context_available"]()),
                               interactive=bool(g["motion_context_available"]()),
                               label="Character Guide", elem_id="cg-on")
        # ？ は gr.HTML（.form の外の部品）。箱の部品（チェック・スライダー）より後に置けば箱は割れない
        g["help_icon"](HELP_CB, anchor="#cg-on label .label-text", elem_id="cg-help")
    elif slot == "system_cards":                                 # SYSTEM タブの箱の並びの最後
        with gr.Column(elem_classes=["panel", "sys-card"], elem_id="cgd-card"):
            gr.Markdown("#### Character Guide（長尺の顔と画づくりを保つ）", elem_id="cgd-title")
            ui["dd"] = gr.Slider(DETAIL_MIN, DETAIL_MAX, step=DETAIL_STEP, value=detail_k(), elem_id="cgd-sl",
                                 label="Detail & Contrast の強さ")
            g["help_icon"](HELP_SYS, anchor="#cgd-title h4", elem_id="cgd-help")


def wire(ctx, comps):
    ui = _ST["ui"]
    if "cb" in ui:
        ui["cb"].change(fn=_set_on, inputs=[ui["cb"]], outputs=None, queue=False, show_progress="hidden")
    if "dd" in ui:
        ui["dd"].release(fn=_set_detail, inputs=[ui["dd"]], outputs=None, queue=False, show_progress="hidden")
