# Copyright (C) 2026 CALMDUST / AiHUB
# SPDX-License-Identifier: Apache-2.0
"""camera3d — 3D の場にマネキンとカメラを置き、キーフレームで動かして灰色のガイド動画を書き出す。MiniMax H3 WebUI の拡張モジュール

設計は WebUI のプロジェクトの camera3d_design_memo.md（2026-10-24）:
  ・利用者の定義: 3D の場に人物の代わりの形（マネキン）とカメラを置き、タイムラインのキーフレームで立ち位置・向き・カメラとの距離を決める。
    動き（演技）は 3D でアニメーションせず、プロンプトで書く。
  ・セル196・197: 灰色のガイド動画を R2V の動画参照（<Video 1>）にすると、人物の位置・姿勢・構図・カメラの動きが付いてくる
    （粗い楕円体でも付いてくる。大きさの対応はゆるい）→ 人体のメッシュ（Quaternius Universal Base Characters、CC0）を灰色で描く。
  ・参考は toyxyz の「minimax h3 camera」の README に書かれた働きだけ（実装は GPL-3.0 なのでコードは読まない・写さない）。

0.1.0（Phase 1）: CAMERA 3D タブ。編集画面（three.js〔MIT〕をブラウザで jsdelivr から版固定で読む）・人（女性／男性）の追加と削除・
       姿勢の決め打ち（立つ・歩く・座る・手を上げる・指さす）・移動／回転・カメラ（カメラから見て回す／全体から動かす）・
       キーフレーム（触ると今の時刻に自動で打つ。なめらか／止まりながら／直線）・再生・ガイドの書き出し
       （ブラウザで 24fps・17n+5 コマを描き、server_functions で 12 コマずつ送って ffmpeg で mp4。シーンの JSON も横に置く）。
       R2V への受け渡し（<Video 1>・人ごとの RefMod → <Subject N>・時刻ごとの挙動の文）は Phase 2。
人体のファイルは同じリポジトリの assets/camera3d/（コミットと sha256 で固定）。本体の _gh_fetch_verified で取り寄せる。
"""
import base64
import datetime
import json
import os
import re
import shutil
import subprocess
import threading
import uuid

NAME = "camera3d"
VERSION = "0.1.0"
API = 1

THREE_VER = "0.170.0"                    # three.js（MIT）。jsdelivr の +esm で読む（アドオンは同じ版の本体を import する）
ASSET_COMMIT = "c521246237b0f2170026711adbc081a44c5a5241"
ASSETS = {                               # 種類 → (リポジトリ内のパス, sha256)
    "f": ("assets/camera3d/human_f.glb", "131716b041b4ab5d729e9b20cf2471a53b2b2115e8b3b8edb43d7a8a093d1f36"),
    "m": ("assets/camera3d/human_m.glb", "bfd23d224538b2737510577f3af395f0da6e5a26542dc28a212582a40f58dc79"),
}
OUT_DIR = "/content/camera3d"            # ガイドの mp4 と JSON の置き場
FPS = 24
GUIDE_SHORT = 480                        # ガイドの短辺（R2V の動画参照は本体が縮めて使う。セル197 は 480 前後で付いてきた）
MAX_SEC = 15.0
MAX_FRAMES = 17 * 21 + 5                 # 362 コマ（約 15 秒）

I18N = {
    # ---- 部品 ----
    "シーン": {"en": "Scene", "zh": "场景", "ko": "장면"},
    "長さ（秒）": {"en": "Length (s)", "zh": "长度（秒）", "ko": "길이(초)"},
    "縦横比": {"en": "Aspect ratio", "zh": "宽高比", "ko": "화면비"},
    "動き方": {"en": "Motion between keys", "zh": "关键帧之间的运动", "ko": "키 사이의 움직임"},
    "なめらか": {"en": "Smooth", "zh": "平滑", "ko": "부드럽게"},
    "キーで止まる": {"en": "Ease at each key", "zh": "每个关键帧处停顿", "ko": "키마다 멈춤"},
    "直線": {"en": "Linear", "zh": "线性", "ko": "직선"},
    "＋ 女性": {"en": "＋ Woman", "zh": "＋ 女性", "ko": "＋ 여성"},
    "＋ 男性": {"en": "＋ Man", "zh": "＋ 男性", "ko": "＋ 남성"},
    "選んだ人を消す": {"en": "Remove selected person", "zh": "删除所选人物", "ko": "선택한 인물 삭제"},
    "姿勢": {"en": "Pose", "zh": "姿势", "ko": "자세"},
    "立つ": {"en": "Standing", "zh": "站立", "ko": "서기"},
    "歩く": {"en": "Walking", "zh": "行走", "ko": "걷기"},
    "座る": {"en": "Sitting", "zh": "坐下", "ko": "앉기"},
    "手を上げる": {"en": "Hand raised", "zh": "举手", "ko": "손 들기"},
    "指さす": {"en": "Pointing", "zh": "指向", "ko": "가리키기"},
    "操作": {"en": "Gizmo", "zh": "操作", "ko": "조작"},
    "移動": {"en": "Move", "zh": "移动", "ko": "이동"},
    "回転": {"en": "Rotate", "zh": "旋转", "ko": "회전"},
    "レンズ（mm）": {"en": "Lens (mm)", "zh": "镜头（mm）", "ko": "렌즈(mm)"},
    "◆ キーを打つ": {"en": "◆ Set key", "zh": "◆ 设置关键帧", "ko": "◆ 키 설정"},
    "◇ キーを消す": {"en": "◇ Delete key", "zh": "◇ 删除关键帧", "ko": "◇ 키 삭제"},
    "🎞 ガイドを書き出す": {"en": "🎞 Export guide", "zh": "🎞 导出引导视频", "ko": "🎞 가이드 내보내기"},
    "GUIDE": {"en": "GUIDE", "zh": "GUIDE", "ko": "GUIDE"},
    "人物とカメラ": {"en": "People and camera", "zh": "人物与摄像机", "ko": "인물과 카메라"},
    # ---- 案内・STATUS ----
    "人は「＋ 女性」「＋ 男性」で足し、画面で押して選びます。時刻を動かしてから人やカメラを動かすと、その時刻にキーが入ります"
    "（「カメラ」の表示では、ドラッグで回り込み・右ドラッグで平行移動・ホイールで寄り引き）。動き（演技）はここでは付けず、生成のプロンプトに書きます。": {
        "en": "Add people with “＋ Woman” / “＋ Man” and click one in the view to select it. Move the playhead, then move a person or the camera: "
              "a key is set at that time (in the “Camera” view, drag to orbit, right-drag to pan, wheel to dolly). "
              "Acting is not animated here — write it in the generation prompt.",
        "zh": "用「＋ 女性」「＋ 男性」添加人物，在画面中点击选择。先移动时间，再移动人物或摄像机，就会在该时刻设置关键帧"
              "（「摄像机」视图中：拖动环绕、右键拖动平移、滚轮推拉）。动作（表演）不在这里制作，请写在生成的提示词里。",
        "ko": "「＋ 여성」「＋ 남성」으로 인물을 추가하고 화면에서 눌러 선택합니다. 시간을 옮긴 뒤 인물이나 카메라를 움직이면 그 시간에 키가 들어갑니다"
              "(「카메라」 보기에서는 드래그로 돌아가기·오른쪽 드래그로 평행 이동·휠로 다가가기/물러나기). 움직임(연기)은 여기서 만들지 않고 생성 프롬프트에 씁니다."},
    "書き出しました: {v0}（{v1}×{v2}・{v3} コマ・{v4} 秒）": {
        "en": "Exported: {v0} ({v1}×{v2}, {v3} frames, {v4} s)",
        "zh": "已导出：{v0}（{v1}×{v2}・{v3} 帧・{v4} 秒）",
        "ko": "내보냈습니다: {v0}({v1}×{v2}・{v3} 프레임・{v4} 초)"},
    "人物 {v0} 人・カメラのキー {v1} 個": {"en": "{v0} person(s), {v1} camera key(s)", "zh": "人物 {v0} 人・摄像机关键帧 {v1} 个",
                                    "ko": "인물 {v0} 명・카메라 키 {v1} 개"},
    "⚠️ 書き出せませんでした: {v0}": {"en": "⚠️ Could not export: {v0}", "zh": "⚠️ 无法导出：{v0}", "ko": "⚠️ 내보낼 수 없었습니다: {v0}"},
    "編集画面がまだ読み込まれていません（CAMERA 3D タブを開いてから押してください）": {
        "en": "The editor is not loaded yet (open the CAMERA 3D tab first)",
        "zh": "编辑器尚未加载（请先打开 CAMERA 3D 标签页）",
        "ko": "편집 화면이 아직 로드되지 않았습니다(CAMERA 3D 탭을 연 뒤 누르세요)"},
    # ---- 編集画面（JS）の文言（c3d_texts で今の言語の訳を渡す）----
    "全体": {"en": "Scene", "zh": "全景", "ko": "전체"},
    "カメラ": {"en": "Camera", "zh": "摄像机", "ko": "카메라"},
    "女性": {"en": "Woman", "zh": "女性", "ko": "여성"},
    "男性": {"en": "Man", "zh": "男性", "ko": "남성"},
    "読み込み中…": {"en": "Loading…", "zh": "加载中…", "ko": "불러오는 중…"},
    "three.js を読み込めませんでした": {"en": "Could not load three.js", "zh": "无法加载 three.js", "ko": "three.js 를 불러올 수 없었습니다"},
    "人体を読み込めませんでした": {"en": "Could not load the mannequin", "zh": "无法加载人体模型", "ko": "인체 모델을 불러올 수 없었습니다"},
    "書き出し中 {v0} / {v1} コマ": {"en": "Exporting {v0} / {v1} frames", "zh": "导出中 {v0} / {v1} 帧", "ko": "내보내는 중 {v0} / {v1} 프레임"},
    "再生": {"en": "Play", "zh": "播放", "ko": "재생"},
    "停止": {"en": "Stop", "zh": "停止", "ko": "정지"},
}

_ST = {"ctx": None, "jobs": {}, "lock": threading.Lock()}
_UI = {}

JS_TEXT_KEYS = ("全体", "カメラ", "女性", "男性", "読み込み中…", "three.js を読み込めませんでした", "人体を読み込めませんでした",
                "書き出し中 {v0} / {v1} コマ", "再生", "停止")


def _g():
    return _ST["ctx"].g


def _T(s, **kw):
    ctx = _ST["ctx"]
    if ctx is None:
        return s.format(**kw) if kw else s
    return ctx.T(s, **kw)


# ------------------------------------------------------------------
#  ブラウザから呼ぶ関数（gr.HTML の server_functions）
# ------------------------------------------------------------------
def c3d_mesh(kind):
    """人体の .glb を base64 で返す（GitHub から版固定で取り寄せ、sha256 を照合した控え）"""
    path, sha = ASSETS["m" if str(kind) == "m" else "f"]
    g = _g()
    local = g["_gh_fetch_verified"](g.get("MODULES_REPO", "core-calmdust/minimax-h3-webui-modules"), ASSET_COMMIT, path, sha,
                                    g.get("MODULES_DIR", "/content/h3_modules"))
    with open(local, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def c3d_texts(_=None):
    """編集画面の文言の、今の言語の訳（server_functions は引数を 1 つ受ける。ブラウザで 2 つ以上渡すと並びになる）"""
    return {k: _T(k) for k in JS_TEXT_KEYS}


def _job_dir(job):
    if not re.fullmatch(r"[0-9a-f]{32}", str(job or "")):
        raise ValueError("bad job")
    return os.path.join(OUT_DIR, ".work", job)


def c3d_begin(spec):
    """書き出しの準備。spec = {w, h, n, scene} → 仕事の番号"""
    spec = dict(spec or {})
    w, h, n = int(spec.get("w", 0)), int(spec.get("h", 0)), int(spec.get("n", 0))
    if not (64 <= w <= 2048 and 64 <= h <= 2048 and 1 <= n <= MAX_FRAMES):
        raise ValueError(f"bad size {w}x{h}x{n}")
    job = uuid.uuid4().hex
    d = _job_dir(job)
    os.makedirs(d, exist_ok=True)
    with _ST["lock"]:
        _ST["jobs"][job] = {"w": w, "h": h, "n": n, "got": set(), "scene": spec.get("scene") or {}}
    return job


def c3d_put(args):
    """[仕事の番号, 始まりのコマ, JPEG の data URL の並び] → start 番目から書く"""
    job, start, frames = list(args)[:3]
    d = _job_dir(job)
    info = _ST["jobs"].get(job)
    if info is None:
        raise ValueError("unknown job")
    start = int(start)
    for i, u in enumerate(list(frames or [])):
        k = start + i
        if not 0 <= k < info["n"]:
            continue
        s = str(u)
        b = base64.b64decode(s.split(",", 1)[1] if s.startswith("data:") else s)
        with open(os.path.join(d, f"{k:05d}.jpg"), "wb") as f:
            f.write(b)
        info["got"].add(k)
    return len(info["got"])


def c3d_finish(job):
    """届いたコマを mp4 にする → mp4 のパス（シーンの JSON を横に置く）"""
    d = _job_dir(job)
    info = _ST["jobs"].pop(job, None)
    if info is None:
        raise ValueError("unknown job")
    try:
        miss = [k for k in range(info["n"]) if k not in info["got"]]
        if miss:
            raise RuntimeError(f"missing frames: {miss[:5]}")
        os.makedirs(OUT_DIR, exist_ok=True)
        stem = "guide_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out = os.path.join(OUT_DIR, stem + ".mp4")
        try:
            ff = _g()["_ffmpeg_exe"]()
        except Exception:                                         # noqa: BLE001
            ff = "ffmpeg"
        cmd = [ff, "-y", "-v", "error", "-framerate", str(FPS), "-i", os.path.join(d, "%05d.jpg"),
               "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p",
               "-r", str(FPS), out]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not os.path.isfile(out):
            raise RuntimeError((r.stderr or "ffmpeg failed").strip()[-300:])
        meta = {"module": f"{NAME} {VERSION}", "w": info["w"], "h": info["h"], "frames": info["n"], "fps": FPS,
                "scene": info["scene"]}
        with open(os.path.join(OUT_DIR, stem + ".json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        return out
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _after_export(res):
    """書き出しボタンの後（JS の結果のパス → GUIDE と STATUS）"""
    s = str(res or "")
    if not s:
        return None, _T("編集画面がまだ読み込まれていません（CAMERA 3D タブを開いてから押してください）")
    if s.startswith("ERR:"):
        return None, _T("⚠️ 書き出せませんでした: {v0}", v0=s[4:].strip())
    if not os.path.isfile(s) or not s.startswith(OUT_DIR + "/"):
        return None, _T("⚠️ 書き出せませんでした: {v0}", v0=s)
    lines = []
    try:
        with open(s[:-4] + ".json", encoding="utf-8") as f:
            m = json.load(f)
        sc = m.get("scene") or {}
        lines.append(_T("書き出しました: {v0}（{v1}×{v2}・{v3} コマ・{v4} 秒）", v0=os.path.basename(s), v1=m["w"], v2=m["h"],
                        v3=m["frames"], v4=f"{m['frames'] / float(FPS):.2f}"))
        lines.append("   " + _T("人物 {v0} 人・カメラのキー {v1} 個", v0=len(sc.get("people") or []),
                                v1=len((sc.get("cam") or {}).get("keys") or [])))
    except Exception:                                             # noqa: BLE001
        lines.append(os.path.basename(s))
    lines.append("   " + s)
    return s, "\n".join(lines)


def _on_bridge(s):
    """JS → Python（読み込んだ・選んだものが変わった・時刻が動いた）→ 長さ・縦横比・動き方・姿勢・レンズの表示を編集画面に合わせる"""
    gr = _ST["ctx"].gr
    try:
        d = json.loads(s or "{}")
    except ValueError:
        d = {}
    keep = gr.update()

    def num(k, lo, hi):
        v = d.get(k)
        return gr.update(value=float(v)) if isinstance(v, (int, float)) and lo <= v <= hi else keep
    return (num("dur", 1, MAX_SEC),
            gr.update(value=d["aspect"]) if d.get("aspect") in ASPECT_KEYS else keep,
            gr.update(value=d["ease"]) if d.get("ease") in EASE_KEYS else keep,
            gr.update(value=d["pose"]) if d.get("pose") in POSE_KEYS else keep,
            num("lens", 10, 200))


POSE_KEYS = ("stand", "walk", "sit", "raise", "point")
ASPECT_KEYS = ("16:9", "9:16", "1:1", "4:3", "3:4")
EASE_KEYS = ("smooth", "ease", "linear")


# ------------------------------------------------------------------
#  編集画面（HTML と JS）
# ------------------------------------------------------------------
HTML_TEMPLATE = """
<div class="c3d-root">
  <div class="c3d-view" tabindex="0">
    <canvas class="c3d-canvas"></canvas>
    <div class="c3d-labels"></div>
    <div class="c3d-bar">
      <button type="button" class="c3d-btn c3d-v-edit" data-view="edit"></button>
      <button type="button" class="c3d-btn c3d-v-cam" data-view="cam"></button>
    </div>
    <div class="c3d-msg"></div>
  </div>
  <div class="c3d-tl">
    <div class="c3d-tl-head">
      <button type="button" class="c3d-btn c3d-play">▶</button>
      <span class="c3d-time">0.00 s</span>
    </div>
    <div class="c3d-tl-body">
      <div class="c3d-tl-names"></div>
      <div class="c3d-tl-track"><div class="c3d-tl-rows"></div><div class="c3d-tl-head-line"></div></div>
    </div>
  </div>
</div>
"""

JS_ON_LOAD = r"""
(async () => {
const host = element.querySelector('.c3d-root');
if (!host || host.dataset.init) return;
host.dataset.init = '1';
const view = host.querySelector('.c3d-view'), canvas = host.querySelector('.c3d-canvas');
const msgEl = host.querySelector('.c3d-msg'), labelsEl = host.querySelector('.c3d-labels');
const namesEl = host.querySelector('.c3d-tl-names'), rowsEl = host.querySelector('.c3d-tl-rows');
const trackEl = host.querySelector('.c3d-tl-track'), headLine = host.querySelector('.c3d-tl-head-line');
const timeEl = host.querySelector('.c3d-time'), playBtn = host.querySelector('.c3d-play');
const FPS = 24, KEY_EPS = 0.5 / FPS, STORE = 'h3.camera3d.scene.v1';
let TX = {};
const tx = (k, kw) => { let s = TX[k] || k; if (kw) for (const [a, b] of Object.entries(kw)) s = s.split('{' + a + '}').join(String(b)); return s; };
const say = (s) => { msgEl.textContent = s || ''; msgEl.style.display = s ? 'block' : 'none'; };
async function loadTexts() { try { TX = await server.c3d_texts(0) || {}; } catch (e) { } paintStatic(); }
function paintStatic() {
  host.querySelector('.c3d-v-edit').textContent = tx('全体');
  host.querySelector('.c3d-v-cam').textContent = tx('カメラ');
  playBtn.title = tx(S && S.playing ? '停止' : '再生');
  if (S) buildRows();
}
let S = null;
say('…');
await loadTexts();
say(tx('読み込み中…'));
const CDN = 'https://cdn.jsdelivr.net/npm/three@__THREE_VER__';
let THREE, GLTFLoader, OrbitControls, TransformControls;
try {
  THREE = await import(CDN + '/+esm');
  ({ GLTFLoader } = await import(CDN + '/examples/jsm/loaders/GLTFLoader.js/+esm'));
  ({ OrbitControls } = await import(CDN + '/examples/jsm/controls/OrbitControls.js/+esm'));
  ({ TransformControls } = await import(CDN + '/examples/jsm/controls/TransformControls.js/+esm'));
} catch (e) { say(tx('three.js を読み込めませんでした') + ': ' + e); return; }

// ---------------- 状態（保存するもの） ----------------
const ASPECTS = { '16:9': [16, 9], '9:16': [9, 16], '1:1': [1, 1], '4:3': [4, 3], '3:4': [3, 4] };
function freshScene() {
  return { v: 1, dur: 5, aspect: '16:9', ease: 'smooth', sel: 'cam', mode: 'translate', view: 'cam', t: 0,
    cam: { keys: [], pos: [0, 1.45, 4.2], tgt: [0, 1.15, 0], lens: 35 },
    people: [
      { id: 'p1', kind: 'f', pose: 'stand', x: -0.55, z: 0, ry: 0.25, keys: [] },
      { id: 'p2', kind: 'm', pose: 'stand', x: 0.55, z: 0, ry: -0.25, keys: [] }] };
}
try { const s = JSON.parse(localStorage.getItem(STORE) || 'null'); if (s && s.v === 1 && s.cam && Array.isArray(s.people)) S = s; } catch (e) { }
if (!S) S = freshScene();
S.playing = false;
let saveTimer = 0;
function save() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => { try { localStorage.setItem(STORE, JSON.stringify(serialize())); } catch (e) { } }, 300);
}
function serialize() {
  const o = JSON.parse(JSON.stringify(S)); delete o.playing; return o;
}

// ---------------- three.js の場 ----------------
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
const scene = new THREE.Scene();
const BG = new THREE.Color().setRGB(130 / 255, 130 / 255, 130 / 255, THREE.SRGBColorSpace);   // ガイドの背景（セル197・Blocking（人物）と同じ灰 130）
scene.background = BG;
scene.add(new THREE.HemisphereLight(0xffffff, 0x4a4a4a, 1.1));
const sun = new THREE.DirectionalLight(0xffffff, 1.6); sun.position.set(-2.5, 5, 4); scene.add(sun);
const grid = new THREE.GridHelper(20, 20, 0x5c5c5c, 0x747474); grid.userData.editorOnly = true; scene.add(grid);
const editCam = new THREE.PerspectiveCamera(45, 1, 0.05, 200); editCam.position.set(4.5, 3.6, 6.5);
const shot = new THREE.PerspectiveCamera(40, 16 / 9, 0.05, 200); shot.filmGauge = 36;
const camHelper = new THREE.CameraHelper(shot); camHelper.userData.editorOnly = true; scene.add(camHelper);
const camBody = new THREE.Mesh(new THREE.BoxGeometry(0.22, 0.16, 0.3), new THREE.MeshBasicMaterial({ color: 0xffaa33 }));
camBody.userData.editorOnly = true; camBody.userData.pick = 'cam'; scene.add(camBody);
const tgtMark = new THREE.Mesh(new THREE.SphereGeometry(0.05, 12, 8), new THREE.MeshBasicMaterial({ color: 0xffaa33 }));
tgtMark.userData.editorOnly = true; scene.add(tgtMark);
const orbitEdit = new OrbitControls(editCam, canvas); orbitEdit.target.set(0, 0.9, 0); orbitEdit.update();
const orbitShot = new OrbitControls(shot, canvas);
const gizmo = new TransformControls(editCam, canvas);
const gizmoHelper = gizmo.getHelper ? gizmo.getHelper() : gizmo;
gizmoHelper.userData.editorOnly = true; scene.add(gizmoHelper);

// 3 段の灰（光の当たり）。人ごとに明るさを替える（セル197: 左は明るい灰・右は暗い灰）
const ramp = new THREE.DataTexture(new Uint8Array([90, 170, 255]), 3, 1, THREE.RedFormat);
ramp.minFilter = ramp.magFilter = THREE.NearestFilter; ramp.needsUpdate = true;
const GRAYS = [0.86, 0.46, 0.68, 0.34, 0.95, 0.56];
function outlineMat() {
  const m = new THREE.MeshBasicMaterial({ color: 0x1b1b1b, side: THREE.BackSide });
  m.onBeforeCompile = (sh) => {
    sh.vertexShader = sh.vertexShader.replace('#include <skinning_vertex>',
      '#include <skinning_vertex>\n transformed += normalize(objectNormal) * 0.011;');
  };
  return m;
}
const OUTLINE = outlineMat();

// ---------------- 人体 ----------------
const meshBuf = {};
async function meshFor(kind) {
  if (!meshBuf[kind]) {
    const b64 = await server.c3d_mesh(kind);
    const bin = atob(b64), u = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
    meshBuf[kind] = u.buffer;
  }
  return await new GLTFLoader().parseAsync(meshBuf[kind].slice(0), '');
}
const POSES = {
  stand: [['upperarm_l', 'z', -72], ['upperarm_r', 'z', 72], ['lowerarm_l', 'y', -10], ['lowerarm_r', 'y', 10]],
  walk: [['upperarm_l', 'z', -74], ['upperarm_r', 'z', 74], ['upperarm_l', 'x', 18], ['upperarm_r', 'x', -18],
    ['lowerarm_l', 'y', -15], ['lowerarm_r', 'y', 15], ['thigh_l', 'x', -22], ['thigh_r', 'x', 16], ['calf_r', 'x', 28], ['calf_l', 'x', 6]],
  sit: [['upperarm_l', 'z', -70], ['upperarm_r', 'z', 70], ['upperarm_l', 'x', -12], ['upperarm_r', 'x', -12],
    ['lowerarm_l', 'x', -55], ['lowerarm_r', 'x', -55], ['thigh_l', 'x', -86], ['thigh_r', 'x', -86], ['calf_l', 'x', 84], ['calf_r', 'x', 84]],
  raise: [['upperarm_l', 'z', -72], ['upperarm_r', 'z', -55], ['lowerarm_l', 'y', -10], ['lowerarm_r', 'z', -55]],
  point: [['upperarm_l', 'z', -72], ['upperarm_r', 'y', 80], ['upperarm_r', 'x', 8], ['lowerarm_l', 'y', -10]],
};
const AX = { x: new THREE.Vector3(1, 0, 0), y: new THREE.Vector3(0, 1, 0), z: new THREE.Vector3(0, 0, 1) };
const RT = new Map();                      // 人の番号 → 描くもの（保存しない）
function applyPose(rt, name) {
  const { wrap, model, bones, rest } = rt;
  for (const [n, q] of Object.entries(rest)) bones[n].quaternion.copy(q);
  model.position.y = 0;
  const sp = wrap.position.clone(), sq = wrap.quaternion.clone();
  wrap.position.set(0, 0, 0); wrap.quaternion.identity(); wrap.updateMatrixWorld(true);
  for (const [n, a, d] of (POSES[name] || [])) {
    const b = bones[n]; if (!b) continue;
    const pq = new THREE.Quaternion(); b.parent.getWorldQuaternion(pq);
    const dq = new THREE.Quaternion().setFromAxisAngle(AX[a], d * Math.PI / 180);
    b.quaternion.premultiply(pq.clone().invert().multiply(dq).multiply(pq));
    b.updateMatrixWorld(true);
  }
  // 足（つま先の付け根）が床から浮かない・沈まないように上下をずらす（座るときは腰が下がる）
  const v = new THREE.Vector3(); let lo = Infinity;
  for (const n of ['ball_l', 'ball_r']) if (bones[n]) { bones[n].getWorldPosition(v); lo = Math.min(lo, v.y); }
  if (isFinite(lo)) model.position.y = rt.footY - lo;
  wrap.position.copy(sp); wrap.quaternion.copy(sq); wrap.updateMatrixWorld(true);
}
function grayOf(i) { return GRAYS[i % GRAYS.length]; }
async function spawn(p) {
  const g = await meshFor(p.kind);
  const wrap = new THREE.Group(), model = g.scene;
  wrap.add(model); scene.add(wrap);
  const bones = {}, rest = {}, skinned = [];
  model.traverse((o) => {
    if (o.isBone) { bones[o.name] = o; rest[o.name] = o.quaternion.clone(); }
    if (o.isSkinnedMesh) skinned.push(o);
  });
  const mat = new THREE.MeshToonMaterial({ color: 0xffffff, gradientMap: ramp });
  for (const sm of skinned) {
    sm.material = mat; sm.frustumCulled = false;
    const ol = new THREE.SkinnedMesh(sm.geometry, OUTLINE); ol.frustumCulled = false;
    ol.bind(sm.skeleton, sm.bindMatrix); ol.bindMode = sm.bindMode; sm.parent.add(ol);
  }
  const pick = new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.3, 1.8, 12), new THREE.MeshBasicMaterial({ visible: false }));
  pick.position.y = 0.9; pick.userData.pick = p.id; wrap.add(pick);
  wrap.updateMatrixWorld(true);
  const v = new THREE.Vector3(); let footY = 0;
  if (bones.ball_l) { bones.ball_l.getWorldPosition(v); footY = v.y; }
  const label = document.createElement('div'); label.className = 'c3d-label'; labelsEl.appendChild(label);
  const rt = { wrap, model, bones, rest, mat, pick, footY, label, pose: null };
  RT.set(p.id, rt);
  return rt;
}
function despawn(id) {
  const rt = RT.get(id); if (!rt) return;
  if (gizmo.object === rt.wrap) gizmo.detach();
  scene.remove(rt.wrap); rt.label.remove(); RT.delete(id);
}

// ---------------- キーフレーム ----------------
const snapT = (t) => Math.max(0, Math.min(S.dur, Math.round(t * FPS) / FPS));
function unwrap(a, ref) { while (a - ref > Math.PI) a -= 2 * Math.PI; while (a - ref < -Math.PI) a += 2 * Math.PI; return a; }
function sample(keys, t, ease) {           // keys: [{t, v:[...]}]（時刻順）→ 補間した v
  if (!keys.length) return null;
  if (keys.length === 1 || t <= keys[0].t) return keys[0].v.slice();
  const L = keys.length - 1;
  if (t >= keys[L].t) return keys[L].v.slice();
  let i = 0; while (i < L - 1 && t >= keys[i + 1].t) i++;
  const a = keys[i], b = keys[i + 1], dt = Math.max(1e-6, b.t - a.t), u = (t - a.t) / dt;
  if (ease === 'linear') return a.v.map((x, j) => x + (b.v[j] - x) * u);
  const h00 = 2 * u * u * u - 3 * u * u + 1, h10 = u * u * u - 2 * u * u + u, h01 = -2 * u * u * u + 3 * u * u, h11 = u * u * u - u * u;
  return a.v.map((x, j) => {
    let m0 = 0, m1 = 0;
    if (ease === 'smooth') {                // 端は 0（ゆっくり始まりゆっくり止まる）・途中は前後の傾き
      if (i > 0) m0 = (b.v[j] - keys[i - 1].v[j]) / Math.max(1e-6, b.t - keys[i - 1].t);
      if (i + 1 < L) m1 = (keys[i + 2].v[j] - x) / Math.max(1e-6, keys[i + 2].t - a.t);
    }
    return h00 * x + h10 * dt * m0 + h01 * b.v[j] + h11 * dt * m1;
  });
}
function camVec(c) {                       // 位置と注視点 → 補間する数（注視点・距離の対数・方位・仰角・レンズ）
  const d = new THREE.Vector3().fromArray(c.pos).sub(new THREE.Vector3().fromArray(c.tgt));
  const r = Math.max(0.05, d.length());
  return [c.tgt[0], c.tgt[1], c.tgt[2], Math.log(r), Math.atan2(d.x, d.z), Math.asin(Math.max(-1, Math.min(1, d.y / r))), c.lens];
}
function camFromVec(v) {
  const r = Math.exp(v[3]), az = v[4], el = v[5];
  const tgt = [v[0], v[1], v[2]];
  return { tgt, pos: [tgt[0] + r * Math.cos(el) * Math.sin(az), tgt[1] + r * Math.sin(el), tgt[2] + r * Math.cos(el) * Math.cos(az)], lens: v[6] };
}
function camKeysV() {
  let prev = null;
  return S.cam.keys.map((k) => { const v = camVec(k); if (prev) v[4] = unwrap(v[4], prev[4]); prev = v; return { t: k.t, v }; });
}
function personKeysV(p) {
  let prev = null;
  return p.keys.map((k) => { const v = [k.x, k.z, k.ry]; if (prev) v[2] = unwrap(v[2], prev[2]); prev = v; return { t: k.t, v }; });
}
function camAt(t) { const v = sample(camKeysV(), t, S.ease); return v ? camFromVec(v) : { pos: S.cam.pos, tgt: S.cam.tgt, lens: S.cam.lens }; }
function personAt(p, t) { const v = sample(personKeysV(p), t, S.ease); return v ? { x: v[0], z: v[1], ry: v[2] } : { x: p.x, z: p.z, ry: p.ry }; }
function setKey(list, t, val) {
  t = snapT(t);
  const i = list.findIndex((k) => Math.abs(k.t - t) < KEY_EPS);
  const k = Object.assign({ t }, val);
  if (i >= 0) list[i] = k; else { list.push(k); list.sort((a, b) => a.t - b.t); }
}
function trackOf(id) { return id === 'cam' ? S.cam : S.people.find((p) => p.id === id); }

// ---------------- 時刻を当てる ----------------
let shotAspect = 16 / 9;
function applyTime(t) {
  const c = camAt(t);
  shot.position.fromArray(c.pos); shot.lookAt(new THREE.Vector3().fromArray(c.tgt));
  shot.aspect = shotAspect; shot.setFocalLength(c.lens); shot.updateProjectionMatrix();
  camBody.position.copy(shot.position); camBody.quaternion.copy(shot.quaternion);
  tgtMark.position.fromArray(c.tgt);
  if (!draggingCam) orbitShot.target.fromArray(c.tgt);
  camHelper.update();
  S.people.forEach((p, i) => {
    const rt = RT.get(p.id); if (!rt) return;
    const q = personAt(p, t);
    rt.wrap.position.set(q.x, 0, q.z); rt.wrap.rotation.set(0, q.ry, 0);
    if (rt.pose !== p.pose) { applyPose(rt, p.pose); rt.pose = p.pose; }
    rt.mat.color.setRGB(grayOf(i), grayOf(i), grayOf(i), THREE.SRGBColorSpace);
    rt.wrap.updateMatrixWorld(true);
  });
}
function setTime(t, quiet) {
  S.t = snapT(t);
  applyTime(S.t);
  timeEl.textContent = S.t.toFixed(2) + ' s';
  placeHead();
  if (!quiet) { bridge(); save(); }
  dirty = true;
}

// ---------------- 選ぶ・動かす ----------------
let draggingCam = false;
function select(id) {
  if (id !== 'cam' && !RT.has(id)) id = 'cam';
  S.sel = id;
  attachGizmo(); buildRows(); bridge(); save(); dirty = true;
}
function attachGizmo() {
  gizmo.detach();
  if (S.view !== 'edit') return;
  if (S.sel === 'cam') {
    gizmo.attach(camBody); gizmo.setMode('translate'); gizmo.showX = gizmo.showY = gizmo.showZ = true;
  } else {
    const rt = RT.get(S.sel); if (!rt) return;
    gizmo.attach(rt.wrap); gizmo.setMode(S.mode === 'rotate' ? 'rotate' : 'translate');
    if (S.mode === 'rotate') { gizmo.showX = false; gizmo.showY = true; gizmo.showZ = false; }
    else { gizmo.showX = true; gizmo.showY = false; gizmo.showZ = true; }
  }
}
function keyNow(id) {                      // 今の見た目を今の時刻のキーにする
  const tr = trackOf(id); if (!tr) return;
  if (id === 'cam') {
    const c = { pos: shot.position.toArray(), tgt: orbitShot.target.toArray(), lens: shot.getFocalLength() };
    if (!S.cam.keys.length) Object.assign(S.cam, c);
    setKey(S.cam.keys, S.t, c);
  } else {
    const rt = RT.get(id); if (!rt) return;
    const v = { x: rt.wrap.position.x, z: rt.wrap.position.z, ry: rt.wrap.rotation.y };
    if (!tr.keys.length) Object.assign(tr, v);
    setKey(tr.keys, S.t, v);
  }
  buildRows(); save(); dirty = true;
}
gizmo.addEventListener('dragging-changed', (e) => {
  orbitEdit.enabled = !e.value;
  if (!e.value) {
    if (S.sel === 'cam') {                  // カメラの体を動かした → 位置だけ変えて注視点はそのまま
      shot.position.copy(camBody.position); shot.lookAt(orbitShot.target);
    }
    keyNow(S.sel); applyTime(S.t);
  }
});
gizmo.addEventListener('objectChange', () => {
  if (S.sel === 'cam') { shot.position.copy(camBody.position); shot.lookAt(orbitShot.target); camHelper.update(); }
  dirty = true;
});
orbitShot.addEventListener('start', () => { draggingCam = true; });
orbitShot.addEventListener('change', () => { camBody.position.copy(shot.position); camBody.quaternion.copy(shot.quaternion); camHelper.update(); dirty = true; });
orbitShot.addEventListener('end', () => { draggingCam = false; S.sel = 'cam'; keyNow('cam'); bridge(); });
orbitEdit.addEventListener('change', () => { dirty = true; });
function setView(v) {
  S.view = v === 'edit' ? 'edit' : 'cam';
  orbitEdit.enabled = S.view === 'edit'; orbitShot.enabled = S.view === 'cam';
  host.querySelectorAll('.c3d-bar .c3d-btn').forEach((b) => b.classList.toggle('c3d-on', b.dataset.view === S.view));
  attachGizmo(); save(); dirty = true;
}
host.querySelectorAll('.c3d-bar .c3d-btn').forEach((b) => b.addEventListener('click', () => setView(b.dataset.view)));
const ray = new THREE.Raycaster();
let downXY = null;
canvas.addEventListener('pointerdown', (e) => { downXY = [e.clientX, e.clientY]; });
canvas.addEventListener('pointerup', (e) => {
  if (!downXY || Math.hypot(e.clientX - downXY[0], e.clientY - downXY[1]) > 4 || gizmo.dragging) { downXY = null; return; }
  downXY = null;
  const rc = canvas.getBoundingClientRect(), vp = viewRect();
  const x = ((e.clientX - rc.left) - vp.x) / vp.w * 2 - 1, y = -(((e.clientY - rc.top) - vp.y) / vp.h * 2 - 1);
  if (Math.abs(x) > 1 || Math.abs(y) > 1) return;
  ray.setFromCamera(new THREE.Vector2(x, y), S.view === 'edit' ? editCam : shot);
  const objs = [];
  RT.forEach((rt) => objs.push(rt.pick));
  if (S.view === 'edit') objs.push(camBody);
  const hit = ray.intersectObjects(objs, false)[0];
  if (hit) select(hit.object.userData.pick);
});
view.addEventListener('keydown', (e) => {
  if (e.key === ' ') { e.preventDefault(); togglePlay(); }
  else if (e.key === 'w' || e.key === 'W') api.setMode('translate');
  else if (e.key === 'e' || e.key === 'E') api.setMode('rotate');
  else if (e.key === 'k' || e.key === 'K') api.keySelected();
});

// ---------------- 描く ----------------
let dirty = true;
function viewRect() {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (S.view !== 'cam') return { x: 0, y: 0, w, h };
  let vw = w, vh = w / shotAspect;
  if (vh > h) { vh = h; vw = h * shotAspect; }
  return { x: (w - vw) / 2, y: (h - vh) / 2, w: vw, h: vh };
}
function setEditorOnly(vis) { scene.traverse((o) => { if (o.userData.editorOnly) o.visible = vis; }); }
function render() {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (!w || !h) return;
  const vp = viewRect();
  renderer.setScissorTest(true);
  renderer.setViewport(0, 0, w, h); renderer.setScissor(0, 0, w, h);
  renderer.setClearColor(0x161618, 1); renderer.clear();
  renderer.setViewport(vp.x, h - vp.y - vp.h, vp.w, vp.h); renderer.setScissor(vp.x, h - vp.y - vp.h, vp.w, vp.h);
  if (S.view === 'cam') {
    setEditorOnly(false);
    renderer.render(scene, shot);
    setEditorOnly(true);
  } else {
    editCam.aspect = w / h; editCam.updateProjectionMatrix();
    camHelper.visible = camBody.visible = tgtMark.visible = true;
    renderer.render(scene, editCam);
  }
  renderer.setScissorTest(false);
  // 人の番号（<Subject N> になる順）
  const cam = S.view === 'cam' ? shot : editCam, v = new THREE.Vector3();
  S.people.forEach((p, i) => {
    const rt = RT.get(p.id); if (!rt) return;
    (rt.bones.Head || rt.wrap).getWorldPosition(v); v.y += 0.28; v.project(cam);
    const on = v.z < 1 && Math.abs(v.x) <= 1.05 && Math.abs(v.y) <= 1.05;
    rt.label.style.display = on ? 'block' : 'none';
    rt.label.textContent = (i + 1) + ' ' + (p.kind === 'm' ? '♂' : '♀');
    rt.label.classList.toggle('c3d-on', S.sel === p.id);
    rt.label.style.left = (vp.x + (v.x + 1) / 2 * vp.w) + 'px';
    rt.label.style.top = (vp.y + (1 - v.y) / 2 * vp.h) + 'px';
  });
}
let lastTs = 0;
function loop(ts) {
  requestAnimationFrame(loop);
  if (S.playing) {
    const dt = lastTs ? (ts - lastTs) / 1000 : 0;
    let t = S.t + dt; if (t > S.dur) t = 0;
    S.t = t; applyTime(t); timeEl.textContent = t.toFixed(2) + ' s'; placeHead(); dirty = true;
  }
  lastTs = ts;
  if (dirty && canvas.clientWidth) { dirty = false; render(); }
}
let lastW = 0;
new ResizeObserver(() => {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (w && h) { renderer.setSize(w, h, false); if (!lastW) loadTexts(); buildRows(); dirty = true; }
  lastW = w;
}).observe(view);
function togglePlay() {
  S.playing = !S.playing; lastTs = 0;
  playBtn.textContent = S.playing ? '❚❚' : '▶'; playBtn.title = tx(S.playing ? '停止' : '再生');
  if (!S.playing) setTime(S.t);
}
playBtn.addEventListener('click', togglePlay);

// ---------------- タイムライン ----------------
function placeHead() { headLine.style.left = (S.t / S.dur * 100) + '%'; }
function buildRows() {
  const rows = [{ id: 'cam', name: tx('カメラ'), keys: S.cam.keys }].concat(
    S.people.map((p, i) => ({ id: p.id, name: (i + 1) + ' ' + tx(p.kind === 'm' ? '男性' : '女性'), keys: p.keys })));
  namesEl.innerHTML = ''; rowsEl.innerHTML = '';
  const ticks = document.createElement('div'); ticks.className = 'c3d-ticks';
  for (let s = 0; s <= Math.floor(S.dur + 1e-6); s++) {
    const k = document.createElement('div'); k.className = 'c3d-tick'; k.style.left = (s / S.dur * 100) + '%';
    const i = document.createElement('i'); i.textContent = s + 's'; k.appendChild(i); ticks.appendChild(k);
  }
  rowsEl.appendChild(ticks);
  for (const r of rows) {
    const n = document.createElement('div'); n.className = 'c3d-name' + (S.sel === r.id ? ' c3d-on' : ''); n.textContent = r.name;
    n.addEventListener('click', () => select(r.id)); namesEl.appendChild(n);
    const row = document.createElement('div'); row.className = 'c3d-row' + (S.sel === r.id ? ' c3d-on' : ''); row.dataset.id = r.id;
    for (const k of r.keys) {
      const d = document.createElement('span'); d.className = 'c3d-key'; d.style.left = (k.t / S.dur * 100) + '%';
      d.title = k.t.toFixed(2) + ' s';
      d.addEventListener('pointerdown', (e) => { e.stopPropagation(); if (S.sel !== r.id) select(r.id); setTime(k.t); });
      row.appendChild(d);
    }
    rowsEl.appendChild(row);
  }
  placeHead();
}
let scrub = false;
function scrubTo(e) {
  const rc = trackEl.getBoundingClientRect();
  setTime(Math.max(0, Math.min(1, (e.clientX - rc.left) / Math.max(1, rc.width))) * S.dur, true);
}
trackEl.addEventListener('pointerdown', (e) => {
  scrub = true; trackEl.setPointerCapture(e.pointerId);
  if (S.playing) togglePlay();
  const row = e.target.closest('.c3d-row'); if (row && row.dataset.id !== S.sel) select(row.dataset.id);
  scrubTo(e);
});
trackEl.addEventListener('pointermove', (e) => { if (scrub) scrubTo(e); });
trackEl.addEventListener('pointerup', () => { if (scrub) { scrub = false; setTime(S.t); } });

// ---------------- 本体の部品とのやりとり ----------------
function bridge() {                        // 選んでいる人の姿勢・今のレンズを Python へ（姿勢とレンズの表示を合わせる）
  const tb = document.querySelector('#c3d-bridge textarea, #c3d-bridge input');
  if (!tb) return;
  const p = S.people.find((q) => q.id === S.sel);
  const val = JSON.stringify({ sel: S.sel, dur: S.dur, aspect: S.aspect, ease: S.ease, pose: p ? p.pose : null, lens: Math.round(camAt(S.t).lens) });
  if (tb.value === val) return;
  tb.value = val; tb.dispatchEvent(new Event('input', { bubbles: true }));
}
const api = {
  set(o) {
    o = o || {};
    if ('dur' in o) { S.dur = Math.max(1, Math.min(15, +o.dur || 5)); S.t = Math.min(S.t, S.dur); }
    if ('aspect' in o && ASPECTS[o.aspect]) { S.aspect = o.aspect; const a = ASPECTS[S.aspect]; shotAspect = a[0] / a[1]; }
    if ('ease' in o) S.ease = o.ease;
    buildRows(); setTime(S.t);
  },
  async addPerson(kind) {
    const id = 'p' + Date.now().toString(36);
    // 今の時刻で誰もいない所（中央から左右へ 0.55m 刻み、空かなければ一歩奥）に置く
    const taken = S.people.map((q) => personAt(q, S.t));
    let x = 0, z = 0;
    found: for (let row = 0; row < 4; row++) for (let i = 0; i < 9; i++) {
      const cx = (i % 2 ? 1 : -1) * 0.55 * Math.ceil(i / 2), cz = -0.8 * row;
      if (taken.every((q) => Math.hypot(q.x - cx, q.z - cz) > 0.5)) { x = cx; z = cz; break found; }
    }
    const p = { id, kind: kind === 'm' ? 'm' : 'f', pose: 'stand', x, z, ry: 0, keys: [] };
    S.people.push(p);
    await spawn(p); rt_pose_reset(p);
    select(id); setTime(S.t);
  },
  removeSelected() {
    const i = S.people.findIndex((p) => p.id === S.sel); if (i < 0) return;
    despawn(S.people[i].id); S.people.splice(i, 1); select('cam'); setTime(S.t);
  },
  setPose(name) {
    const p = S.people.find((q) => q.id === S.sel); if (!p || !POSES[name]) return;
    p.pose = name; setTime(S.t);
  },
  setMode(m) { S.mode = m === 'rotate' ? 'rotate' : 'translate'; if (S.sel !== 'cam') attachGizmo(); save(); dirty = true; },
  setLens(mm) {
    mm = Math.max(10, Math.min(200, +mm || 35));
    shot.setFocalLength(mm); shot.updateProjectionMatrix(); camHelper.update();
    S.sel = 'cam'; keyNow('cam'); setTime(S.t, true); buildRows();
  },
  keySelected() { keyNow(S.sel); },
  deleteKey() {
    const tr = trackOf(S.sel); if (!tr) return;
    const i = tr.keys.findIndex((k) => Math.abs(k.t - S.t) < KEY_EPS);
    if (i >= 0) {
      const k = tr.keys.splice(i, 1)[0];
      if (!tr.keys.length) Object.assign(tr, S.sel === 'cam' ? { pos: k.pos, tgt: k.tgt, lens: k.lens } : { x: k.x, z: k.z, ry: k.ry });
    }
    buildRows(); setTime(S.t);
  },
  async exportGuide() {
    if (S.playing) togglePlay();
    const a = ASPECTS[S.aspect] || [16, 9], G = __GUIDE_SHORT__;
    let W, H;
    if (a[0] >= a[1]) { H = G; W = Math.round(G * a[0] / a[1] / 2) * 2; } else { W = G; H = Math.round(G * a[1] / a[0] / 2) * 2; }
    const n = Math.max(22, Math.min(__MAX_FRAMES__, Math.round((S.dur * FPS - 5) / 17) * 17 + 5));
    const job = await server.c3d_begin({ w: W, h: H, n, scene: serialize() });
    const cv = document.createElement('canvas'); cv.width = W; cv.height = H;
    const r2 = new THREE.WebGLRenderer({ canvas: cv, antialias: true, preserveDrawingBuffer: true });
    r2.setPixelRatio(1); r2.setSize(W, H, false);
    const keepT = S.t, keepAspect = shotAspect;
    shotAspect = W / H;
    setEditorOnly(false);
    try {
      let batch = [], start = 0;
      for (let i = 0; i < n; i++) {
        applyTime(Math.min(S.dur, i / FPS));
        r2.render(scene, shot);
        batch.push(cv.toDataURL('image/jpeg', 0.92));
        if (batch.length === 12 || i === n - 1) {
          say(tx('書き出し中 {v0} / {v1} コマ', { v0: i + 1, v1: n }));
          await server.c3d_put(job, start, batch); start = i + 1; batch = [];
        }
      }
      return await server.c3d_finish(job);
    } finally {
      setEditorOnly(true); shotAspect = keepAspect; r2.dispose(); try { r2.forceContextLoss(); } catch (e) { }
      say(''); setTime(keepT, true);
    }
  },
};
function rt_pose_reset(p) { const rt = RT.get(p.id); if (rt) rt.pose = null; }
window.__c3d = api;

// ---------------- 始める ----------------
try {
  for (const p of S.people) await spawn(p);
} catch (e) { say(tx('人体を読み込めませんでした') + ': ' + e); return; }
{ const a = ASPECTS[S.aspect] || [16, 9]; shotAspect = a[0] / a[1]; }
say('');
setView(S.view); select(S.sel); setTime(S.t);
host.dataset.ready = '1';
requestAnimationFrame(loop);
})();
"""


def _js():
    return (JS_ON_LOAD.replace("__THREE_VER__", THREE_VER).replace("__GUIDE_SHORT__", str(int(GUIDE_SHORT)))
            .replace("__MAX_FRAMES__", str(int(MAX_FRAMES))))


# 書き出しボタン: JS で描いて送り、できた mp4 のパスを Python へ渡す
EXPORT_JS = """
async (x) => {
  try {
    if (!window.__c3d) return '';
    return await window.__c3d.exportGuide();
  } catch (e) { return 'ERR: ' + (e && e.message ? e.message : e); }
}
"""


def _call_js(expr):
    return "(...a) => { try { if (window.__c3d) { " + expr + " } } catch (e) { console.error(e); } return a.length > 1 ? a : a[0]; }"


# ------------------------------------------------------------------
#  書式（本体の SEGMENTS の箱を写す＋編集画面の中身）
# ------------------------------------------------------------------
_MIRROR = {                                                       # SEGMENTS の id → CAMERA 3D の id
    "#seg-left": ["#c3d-left"], "#seg-right": ["#c3d-right"],
    "#seg-preview-box": ["#c3d-view-box", "#c3d-out-box"],
    "#seg-act": ["#c3d-scene", "#c3d-obj"],
    "#seg-concat-btn": ["#c3d-add-f", "#c3d-add-m", "#c3d-del", "#c3d-key", "#c3d-unkey", "#c3d-export"],
    "#seg-len": ["#c3d-dur", "#c3d-lens"],
    "#status-panel": ["#c3d-status"], "#lora-dd": ["#c3d-aspect", "#c3d-ease", "#c3d-pose", "#c3d-mode"],
    "#seg-note": ["#c3d-note"],
}
CSS = ""
CSS_EXTRA = """
#c3d-bridge, #c3d-res { display: none !important; }
#c3d-left { justify-content: flex-start !important; }
#c3d-left > * { flex: 0 0 auto !important; }
#c3d-scene > *, #c3d-obj > * { margin-top: 0 !important; }
#c3d-status { margin-left: 12px !important; margin-right: 12px !important; width: calc(100% - 24px) !important; min-width: 0 !important; flex-grow: 0 !important; }
#c3d-btns, #c3d-keys { gap: 8px !important; flex-wrap: nowrap !important; }
#c3d-btns > *, #c3d-keys > * { min-width: 0 !important; }
#c3d-view-box { padding-top: 10px !important; }
/* 編集画面（three.js）。枠と角は Keyframe のプレビューとタイムライン（#kf-preview・#kf-list）に合わせる */
#c3d-editor .c3d-root { display: flex; flex-direction: column; gap: 8px; }
#c3d-editor .c3d-view { position: relative; width: 100%; aspect-ratio: 16 / 10; max-height: 440px; border: 1px solid var(--h3-border); border-radius: 10px;
    overflow: hidden; background: #161618; outline: none; }
#c3d-editor .c3d-canvas { display: block; width: 100%; height: 100%; touch-action: none; }
#c3d-editor .c3d-bar { position: absolute; top: 8px; left: 8px; display: flex; gap: 6px; }
#c3d-editor .c3d-btn { height: 26px; padding: 0 10px; border-radius: 6px; border: 1px solid var(--h3-border2);
    background: var(--h3-icon-btn); color: var(--h3-muted); font-size: 11px; letter-spacing: 0.04em; cursor: pointer; }
#c3d-editor .c3d-btn:hover { background: var(--h3-elev); border-color: var(--h3-border-hover); color: var(--h3-text); }
#c3d-editor .c3d-btn.c3d-on { border-color: var(--h3-accent); color: var(--h3-accent-text); }
#c3d-editor .c3d-msg { display: none; position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);
    padding: 6px 12px; border-radius: 6px; background: var(--h3-caption-bg); color: var(--h3-text3); font-size: 12px; }
#c3d-editor .c3d-labels { position: absolute; inset: 0; pointer-events: none; overflow: hidden; }
#c3d-editor .c3d-label { position: absolute; transform: translate(-50%, -100%); padding: 1px 6px; border-radius: 4px;
    background: var(--h3-caption-bg); color: var(--h3-muted); font-size: 10px; white-space: nowrap; }
#c3d-editor .c3d-label.c3d-on { color: var(--h3-accent-text); box-shadow: inset 0 0 0 1px var(--h3-accent); }
#c3d-editor .c3d-tl { user-select: none; -webkit-user-select: none; }
#c3d-editor .c3d-tl-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
#c3d-editor .c3d-time { font-size: 12px; color: var(--h3-text3); font-variant-numeric: tabular-nums; }
#c3d-editor .c3d-tl-body { display: flex; gap: 8px; }
#c3d-editor .c3d-tl-names { flex: 0 0 auto; padding-top: 16px; }
#c3d-editor .c3d-name { height: 24px; line-height: 24px; font-size: 11px; color: var(--h3-muted); letter-spacing: 0.04em;
    white-space: nowrap; cursor: pointer; }
#c3d-editor .c3d-name.c3d-on { color: var(--h3-accent-text); }
#c3d-editor .c3d-tl-track { position: relative; flex: 1 1 auto; min-width: 0; padding-top: 16px; border: 1px solid var(--h3-border);
    border-radius: 10px; background: var(--h3-kf-track, var(--h3-elev)); touch-action: none; overflow: hidden; cursor: pointer; }
#c3d-editor .c3d-ticks { position: absolute; inset: 0; pointer-events: none; }
#c3d-editor .c3d-tick { position: absolute; top: 0; bottom: 0; width: 0; border-left: 1px dashed var(--h3-border2); }
#c3d-editor .c3d-tick i { position: absolute; top: 2px; left: 3px; font-style: normal; font-size: 10px; color: var(--h3-faint); white-space: nowrap; }
#c3d-editor .c3d-tick:first-child { border-left: none; }
#c3d-editor .c3d-tick:last-child i { left: auto; right: 3px; }
#c3d-editor .c3d-row { position: relative; height: 24px; margin: 0 8px; }
#c3d-editor .c3d-row.c3d-on { background: var(--h3-accent-soft); border-radius: 4px; }
#c3d-editor .c3d-key { position: absolute; top: 50%; width: 9px; height: 9px; margin: -5px 0 0 -5px; transform: rotate(45deg);
    background: var(--h3-border3); border: 1px solid var(--h3-muted); box-sizing: border-box; cursor: pointer; }
#c3d-editor .c3d-row.c3d-on .c3d-key { background: var(--h3-accent); border-color: var(--h3-accent-2); }
#c3d-editor .c3d-tl-head-line { position: absolute; top: 0; bottom: 0; width: 0; border-left: 2px solid var(--h3-accent);
    margin-left: -1px; pointer-events: none; }
"""

HELP_C3D = ("3D の場に人（マネキン）とカメラを置き、時刻ごとの立ち位置・向き・カメラの位置をキーフレームで決めて、灰色のガイド動画を書き出します。"
            "ガイドを R2V の動画参照にすると、人物の位置・姿勢・構図・カメラの動きがガイドに付いてきます（セル196・197）。\n"
            "人は「＋ 女性」「＋ 男性」で足し、画面で押して選びます。「全体」の表示では矢印で動かし（操作＝回転で向きを変える）、"
            "「カメラ」の表示ではドラッグで回り込み・右ドラッグで平行移動・ホイールで寄り引きします。"
            "時刻を動かしてから人やカメラを動かすと、その時刻にキーが入ります（キーが 1 つも無いものは止まったまま）。\n"
            "動き（演技）はここでは付けず、生成のプロンプトに書きます。ガイドは 24fps・17n＋5 コマ・短辺 480 で /content/camera3d/ に書き出します"
            "（シーンの JSON も同じ名前で横に置きます）")

I18N.update({
    HELP_C3D: {
        "en": "Place people (mannequins) and a camera in 3D, set where they stand, which way they face and where the camera is at each time "
              "with keyframes, and export a gray guide video. Used as the R2V video reference, the guide drives the people's positions, poses, "
              "framing and camera move (cells 196–197).\n"
              "Add people with “＋ Woman” / “＋ Man” and click one in the view to select it. In the “Scene” view drag the arrows "
              "(Gizmo = Rotate turns them); in the “Camera” view drag to orbit, right-drag to pan and use the wheel to dolly. "
              "Move the playhead first, then move a person or the camera to set a key at that time (anything with no keys stays still).\n"
              "Acting is not animated here — write it in the generation prompt. Guides are exported at 24 fps, 17n+5 frames, short side 480, "
              "to /content/camera3d/ (with the scene JSON next to them).",
        "zh": "在 3D 场景中放置人物（人体模型）和摄像机，用关键帧决定每个时刻的站位、朝向和摄像机位置，并导出灰色的引导视频。"
              "把引导视频作为 R2V 的视频参考，人物的位置、姿势、构图和摄像机运动会跟随引导（单元 196・197）。\n"
              "用「＋ 女性」「＋ 男性」添加人物，在画面中点击选择。在「全景」视图中拖动箭头移动（操作＝旋转可改变朝向），"
              "在「摄像机」视图中拖动环绕、右键拖动平移、滚轮推拉。先移动时间，再移动人物或摄像机，就会在该时刻设置关键帧（没有关键帧的对象保持不动）。\n"
              "动作（表演）不在这里制作，请写在生成的提示词里。引导视频以 24fps・17n+5 帧・短边 480 导出到 /content/camera3d/（同名的场景 JSON 放在旁边）。",
        "ko": "3D 공간에 인물(마네킹)과 카메라를 놓고, 시간마다 서는 위치·방향·카메라 위치를 키프레임으로 정해 회색 가이드 영상을 내보냅니다. "
              "가이드를 R2V 의 영상 참조로 쓰면 인물의 위치·자세·구도·카메라 움직임이 가이드를 따라옵니다(셀 196・197).\n"
              "「＋ 여성」「＋ 남성」으로 인물을 추가하고 화면에서 눌러 선택합니다. 「전체」 보기에서는 화살표로 움직이고(조작＝회전으로 방향 변경), "
              "「카메라」 보기에서는 드래그로 돌아가기·오른쪽 드래그로 평행 이동·휠로 다가가기/물러나기를 합니다. "
              "시간을 먼저 옮긴 뒤 인물이나 카메라를 움직이면 그 시간에 키가 들어갑니다(키가 하나도 없는 것은 멈춘 채로).\n"
              "움직임(연기)은 여기서 만들지 않고 생성 프롬프트에 씁니다. 가이드는 24fps・17n+5 프레임・짧은 변 480 으로 /content/camera3d/ 에 내보냅니다"
              "(같은 이름의 장면 JSON 도 옆에 둡니다)."},
})


def _mirror_css(css):
    """本体の CSS から、_MIRROR の id だけで書かれた規則を写す（media_context と同じ考え。本体のコードは写していない）"""
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
            if not hit or any(x not in _MIRROR for x in ids):
                continue
            outs = [one]
            for x in hit:
                outs = [o.replace(x, y) for o in outs for y in _MIRROR[x]]
            keep += outs
        if keep:
            out.append(",\n".join(dict.fromkeys(keep)) + " {" + block + "}")
    return "\n".join(out)


def setup(ctx):
    global CSS
    _ST["ctx"] = ctx
    try:
        CSS = "\n/* ---- CAMERA 3D（camera3d。SEGMENTS の写し） ---- */\n" + _mirror_css(ctx.g.get("CUSTOM_CSS", "")) + CSS_EXTRA
    except Exception:                                             # noqa: BLE001
        CSS = CSS_EXTRA


SLOTS = ("main_tabs",)


def build_slot(ctx, slot):
    if slot != "main_tabs":
        return
    gr = ctx.gr
    g = ctx.g
    with gr.Tab("CAMERA 3D", id="tab-camera3d"):
        with gr.Row(equal_height=False):
            with gr.Column(scale=2, elem_id="c3d-left"):
                with gr.Column(elem_classes=["panel"], elem_id="c3d-view-box"):
                    _UI["editor"] = gr.HTML(value="", html_template=HTML_TEMPLATE, js_on_load=_js(), elem_id="c3d-editor",
                                            apply_default_css=False,
                                            server_functions=[c3d_mesh, c3d_texts, c3d_begin, c3d_put, c3d_finish])
                gr.Markdown("人は「＋ 女性」「＋ 男性」で足し、画面で押して選びます。時刻を動かしてから人やカメラを動かすと、その時刻にキーが入ります"
                            "（「カメラ」の表示では、ドラッグで回り込み・右ドラッグで平行移動・ホイールで寄り引き）。動き（演技）はここでは付けず、生成のプロンプトに書きます。",
                            elem_id="c3d-note")
            with gr.Column(scale=1, elem_id="c3d-right"):
                with gr.Column(elem_classes=["panel"], elem_id="c3d-scene"):
                    _UI["dur"] = gr.Slider(2.0, MAX_SEC, value=5.0, step=0.5, label="長さ（秒）", elem_id="c3d-dur")
                    _UI["aspect"] = gr.Dropdown(choices=list(ASPECT_KEYS), value="16:9", label="縦横比",
                                                elem_id="c3d-aspect", container=True, filterable=False)
                    _UI["ease"] = gr.Dropdown(choices=[("なめらか", "smooth"), ("キーで止まる", "ease"), ("直線", "linear")],
                                              value="smooth", label="動き方", elem_id="c3d-ease", container=True, filterable=False)
                    _UI["lens"] = gr.Slider(14, 135, value=35, step=1, label="レンズ（mm）", elem_id="c3d-lens")
                with gr.Column(elem_classes=["panel"], elem_id="c3d-obj"):
                    _UI["pose"] = gr.Dropdown(choices=[("立つ", "stand"), ("歩く", "walk"), ("座る", "sit"), ("手を上げる", "raise"),
                                                       ("指さす", "point")], value="stand", label="姿勢", elem_id="c3d-pose",
                                              container=True, filterable=False)
                    _UI["mode"] = gr.Dropdown(choices=[("移動", "translate"), ("回転", "rotate")], value="translate", label="操作",
                                              elem_id="c3d-mode", container=True, filterable=False)
                    with gr.Row(elem_id="c3d-btns"):
                        _UI["add_f"] = gr.Button("＋ 女性", elem_id="c3d-add-f")
                        _UI["add_m"] = gr.Button("＋ 男性", elem_id="c3d-add-m")
                    _UI["del"] = gr.Button("選んだ人を消す", elem_id="c3d-del")
                    with gr.Row(elem_id="c3d-keys"):
                        _UI["key"] = gr.Button("◆ キーを打つ", elem_id="c3d-key")
                        _UI["unkey"] = gr.Button("◇ キーを消す", elem_id="c3d-unkey")
                with gr.Column(elem_classes=["panel"], elem_id="c3d-status"):
                    _UI["msg"] = gr.Textbox(label="STATUS", lines=4, max_lines=int(g.get("STATUS_MAX_LINES", 200)),
                                            interactive=False, value="")
                with gr.Column(elem_classes=["panel"], elem_id="c3d-out-box"):
                    _UI["export"] = gr.Button("🎞 ガイドを書き出す", elem_id="c3d-export")
                    _UI["out"] = gr.Video(label="GUIDE", autoplay=True, loop=True, height=int(g.get("SEG_BOX_H", 360)) * 2 // 3,
                                          interactive=False, elem_id="c3d-out-video", buttons=g.get("BTN_MEDIA"))
                _UI["bridge"] = gr.Textbox(value="", elem_id="c3d-bridge", show_label=False, container=False)
                _UI["res"] = gr.Textbox(value="", elem_id="c3d-res", show_label=False, container=False)
        hi = g.get("help_icon")
        if hi is not None:
            try:
                hi(HELP_C3D, anchor="#c3d-dur label > span:first-child", elem_id="c3d-help")
            except Exception:                                     # noqa: BLE001
                pass
    _wire()


def _wire():
    u = _UI
    u["dur"].input(None, inputs=[u["dur"]], js=_call_js("window.__c3d.set({dur: a[0]});"))
    u["aspect"].input(None, inputs=[u["aspect"]], js=_call_js("window.__c3d.set({aspect: a[0]});"))
    u["ease"].input(None, inputs=[u["ease"]], js=_call_js("window.__c3d.set({ease: a[0]});"))
    u["add_f"].click(None, js=_call_js("window.__c3d.addPerson('f');"))
    u["add_m"].click(None, js=_call_js("window.__c3d.addPerson('m');"))
    u["del"].click(None, js=_call_js("window.__c3d.removeSelected();"))
    u["pose"].input(None, inputs=[u["pose"]], js=_call_js("window.__c3d.setPose(a[0]);"))
    u["mode"].input(None, inputs=[u["mode"]], js=_call_js("window.__c3d.setMode(a[0]);"))
    u["lens"].input(None, inputs=[u["lens"]], js=_call_js("window.__c3d.setLens(a[0]);"))
    u["key"].click(None, js=_call_js("window.__c3d.keySelected();"))
    u["unkey"].click(None, js=_call_js("window.__c3d.deleteKey();"))
    u["bridge"].change(_on_bridge, inputs=[u["bridge"]], outputs=[u["dur"], u["aspect"], u["ease"], u["pose"], u["lens"]], queue=False, show_progress="hidden")
    u["export"].click(_after_export, inputs=[u["res"]], outputs=[u["out"], u["msg"]], js=EXPORT_JS, show_progress="minimal")


def wire(ctx, comps):
    return
