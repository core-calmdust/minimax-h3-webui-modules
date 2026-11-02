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
0.2.0（Phase 2）: セル198〜201 の結果で、ガイドは「動画参照のまま短辺 256 で読む」（生成の間だけ canvas_short_edge=256）。
       768p より速く（177→61 秒）ガイドに忠実（人の IoU 0.40→0.57）。192 以下は崩れ始める（128 で 0.33）。物（箱）は言葉の位置で足りる。
       CAMERA 3D タブに「🎬 生成」: ガイドを書き出して R2V へ <Video 1>（weak_reference）として渡す。人ごとに RefMod を割り当て
       （人の番号の順）→ <Subject N>（説明は refmod_tools の @character N。説明が無ければラベルだけ）、場所と時刻つきの動き・セリフから
       6 節のプロンプトを組む（人の立ち位置は書き出しの最初・最後のコマで画面の左・中央・右を測って書く）。Turbo・Steps は CREATE の今の設定。
       結果は LIBRARY（/content）にメタつきで残る。生成は本体の生成と直列（concurrency_id="generate"）。
0.3.0: 利用者要望（2026-11-02）「キーフレームの画像から人物を認識して 3D カメラにする。画像はコマとして使うことも使わないことも出来る」。
       編集画面に「🖼 画像」（下敷き。カメラの表示に半透明で重ね、濃さを切り替え）と「👤 画像から配置」:
       MediaPipe Pose Landmarker（Apache-2.0、jsdelivr の tasks-vision と Google の公開モデルをブラウザで読む）で人の関節を取り、
       胴（肩の中点〜腰の中点）の長さ〔世界座標 m ÷ 画素〕とレンズから距離、胴の向きからカメラの俯き、腰の高さ（立ち 0.92m／座り 0.5m）から
       カメラの高さ、肩の向きから体の向き、膝・腰・手首から姿勢（立つ・座る・歩く・手を上げる）を決めて、今の時刻のキーとして置く（人数も合わせる）。
       生成の箱に「画像を最初のコマにする」: 本体の R2V のキーフレーム（kf_prepare → _run_pipe(kf_entries=)）で 0 秒に置く。⏳ セル203 で確認中
0.4.0: カット割り（利用者要望 2026-11-01／セル202: カットを起こすのはプロンプトの [Shot N] 分け、ガイドのカットだけでは切り替わらない。
       ガイドは時刻と構図を少し引き寄せる。書いた時刻より 0.4〜0.5 秒遅れて切り替わる）。
       「✂ カット」で再生位置からショットを割る（カメラの補間はカットをまたがない。前のショットの動きは保ち、新しいショットはカットの時刻の
       カメラから始まる）。タイムラインにショットの境目と S1・S2…。書き出しはショットごとに真ん中のコマで構図（全身／膝上／腰上／胸上／顔の寄り）と
       映っている人・左右を測る。プロンプトは動き・セリフの時刻つきの文をカットの時刻で [Shot N] に分け、ショットの頭に構図と「hard cut」を書く。
       プロンプトに書くカットの時刻は CUT_LEAD 秒だけ前倒し（セル202 の遅れ 0.42／0.54 秒から。⏳ 実機で狙いの時刻に入るか確かめる）
0.4.1: 利用者報告「⏳ 生成中 4/4 steps で止まった」（パイプラインは終わっていた＝後の書き出しで止まった／例外が STATUS に出ない）。
       生成の後の書き出し（コマ → mp4・音・メタ）を try で包み、失敗したら理由を STATUS に出す。書き出しの前に「📼 書き出しています…」を出す。
       コマの変換は本体の生成と同じく、PIL でも配列（uint8／0〜1 の小数）でもそのまま export_to_video に渡せる形にそろえる
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
VERSION = "0.4.1"
API = 1

THREE_VER = "0.170.0"                    # three.js（MIT）。jsdelivr の +esm で読む（アドオンは同じ版の本体を import する）
ASSET_COMMIT = "c521246237b0f2170026711adbc081a44c5a5241"
ASSETS = {                               # 種類 → (リポジトリ内のパス, sha256)
    "f": ("assets/camera3d/human_f.glb", "131716b041b4ab5d729e9b20cf2471a53b2b2115e8b3b8edb43d7a8a093d1f36"),
    "m": ("assets/camera3d/human_m.glb", "bfd23d224538b2737510577f3af395f0da6e5a26542dc28a212582a40f58dc79"),
}
OUT_DIR = "/content/camera3d"            # ガイドの mp4 と JSON の置き場
FPS = 24
GUIDE_SHORT = 480                        # ガイドの書き出しの短辺（見るため。生成では下の GUIDE_READ_EDGE で読む）
GUIDE_READ_EDGE = 256                    # 0.2.0 生成でガイドを読む短辺（セル200・201: 256 が最も忠実で速い。192 以下は崩れ始める）
MAX_SEC = 15.0
MAX_FRAMES = 17 * 21 + 5                 # 362 コマ（約 15 秒）
CUT_LEAD = 0.4                           # 0.4.0 プロンプトのカットの時刻を前倒しにする秒（セル202: 書いた時刻より 0.42〜0.54 秒遅れて切り替わった）
MP_VER = "0.10.14"                       # 0.3.0 @mediapipe/tasks-vision（Apache-2.0）
MP_MODEL = ("https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/"
            "pose_landmarker_lite.task")

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
    # ---- 0.4.0 カット ----
    "✂ カット": {"en": "✂ Cut", "zh": "✂ 剪切", "ko": "✂ 컷"},
    "カットを消す": {"en": "Remove cut", "zh": "删除剪切", "ko": "컷 삭제"},
    # ---- 0.3.0 画像 ----
    "🖼 画像": {"en": "🖼 Image", "zh": "🖼 图像", "ko": "🖼 이미지"},
    "👤 画像から配置": {"en": "👤 Place from image", "zh": "👤 按图像摆放", "ko": "👤 이미지에서 배치"},
    "下敷き": {"en": "Overlay", "zh": "底图", "ko": "밑그림"},
    "人を探しています…": {"en": "Finding people…", "zh": "正在寻找人物…", "ko": "인물을 찾는 중…"},
    "人を認識できませんでした": {"en": "Could not detect people", "zh": "无法识别人物", "ko": "인물을 인식하지 못했습니다"},
    "画像に人が見つかりませんでした": {"en": "No people found in the image", "zh": "图像中没有找到人物", "ko": "이미지에서 인물을 찾지 못했습니다"},
    "画像を最初のコマにする": {"en": "Use the image as the first frame", "zh": "把图像作为第一帧", "ko": "이미지를 첫 프레임으로 사용"},
    "🖼 画像を最初のコマにします（0 秒のキーフレーム）": {"en": "🖼 Using the image as the first frame (keyframe at 0 s)",
                                               "zh": "🖼 把图像作为第一帧（0 秒的关键帧）", "ko": "🖼 이미지를 첫 프레임으로 사용합니다(0 초 키프레임)"},
    "⚠️ 最初のコマにする画像がありません（編集画面の「🖼 画像」で読み込んでください）": {
        "en": "⚠️ No image for the first frame (load one with “🖼 Image” in the editor)",
        "zh": "⚠️ 没有作为第一帧的图像（请在编辑器中用「🖼 图像」读取）",
        "ko": "⚠️ 첫 프레임으로 쓸 이미지가 없습니다(편집 화면의 「🖼 이미지」로 불러오세요)"},
    "⚠️ キーフレームを用意できませんでした: {v0}": {"en": "⚠️ Could not prepare the keyframe: {v0}", "zh": "⚠️ 无法准备关键帧：{v0}",
                                         "ko": "⚠️ 키프레임을 준비할 수 없었습니다: {v0}"},
    # ---- 0.2.0 生成 ----
    "人物の RefMod（人の番号の順）": {"en": "People's RefMods (in person order)", "zh": "人物的 RefMod（按人物编号顺序）", "ko": "인물의 RefMod(인물 번호 순서)"},
    "場所・背景": {"en": "Place / background", "zh": "地点・背景", "ko": "장소・배경"},
    "動き・セリフ（時刻つき）": {"en": "Actions / lines (with times)", "zh": "动作・台词（带时间）", "ko": "움직임・대사(시간 포함)"},
    "Seed（−1 でランダム）": {"en": "Seed (−1 = random)", "zh": "Seed（−1 为随机）", "ko": "Seed(−1 은 랜덤)"},
    "🎬 生成": {"en": "🎬 Generate", "zh": "🎬 生成", "ko": "🎬 생성"},
    "例: a cozy bookstore cafe in the afternoon, wooden bookshelves along the left wall": {
        "en": "e.g. a cozy bookstore cafe in the afternoon, wooden bookshelves along the left wall",
        "zh": "例：a cozy bookstore cafe in the afternoon, wooden bookshelves along the left wall",
        "ko": "예: a cozy bookstore cafe in the afternoon, wooden bookshelves along the left wall"},
    "例: 0-2s: <Subject 1> waves and says <d>[Japanese] おはよう</d> 2-5s: <Subject 2> laughs.": {
        "en": "e.g. 0-2s: <Subject 1> waves and says <d>[Japanese] おはよう</d> 2-5s: <Subject 2> laughs.",
        "zh": "例：0-2s: <Subject 1> waves and says <d>[Japanese] おはよう</d> 2-5s: <Subject 2> laughs.",
        "ko": "예: 0-2s: <Subject 1> waves and says <d>[Japanese] おはよう</d> 2-5s: <Subject 2> laughs."},
    "⚠️ RefMod が無い人は言葉だけで描きます（{v0} 人中 {v1} 人に RefMod）": {
        "en": "⚠️ People without a RefMod are drawn from words only ({v1} of {v0} have a RefMod)",
        "zh": "⚠️ 没有 RefMod 的人物只按文字绘制（{v0} 人中 {v1} 人有 RefMod）",
        "ko": "⚠️ RefMod 가 없는 인물은 글로만 그립니다({v0} 명 중 {v1} 명에 RefMod)"},
    "ℹ️ 人 {v0}（{v1}）は見た目の説明が無いのでラベルだけで指します（FINDER で説明を付けると似やすくなります）": {
        "en": "ℹ️ Person {v0} ({v1}) has no appearance description, so only the label is used (adding one in FINDER helps the likeness)",
        "zh": "ℹ️ 人物 {v0}（{v1}）没有外貌描述，只用标签指代（在 FINDER 中添加描述会更像）",
        "ko": "ℹ️ 인물 {v0}({v1})은 외모 설명이 없어 라벨만으로 가리킵니다(FINDER 에서 설명을 붙이면 더 닮습니다)"},
    "⚠️ ラベルを展開できませんでした: {v0}": {"en": "⚠️ Could not expand the labels: {v0}", "zh": "⚠️ 无法展开标签：{v0}", "ko": "⚠️ 라벨을 펼칠 수 없었습니다: {v0}"},
    "🎬 R2V: {v0}×{v1}・{v2} コマ・seed {v3}・{v4}・Steps {v5}・ガイドは短辺 {v6} で読みます": {
        "en": "🎬 R2V: {v0}×{v1}, {v2} frames, seed {v3}, {v4}, Steps {v5}, guide read at short side {v6}",
        "zh": "🎬 R2V：{v0}×{v1}・{v2} 帧・seed {v3}・{v4}・Steps {v5}・引导以短边 {v6} 读取",
        "ko": "🎬 R2V: {v0}×{v1}・{v2} 프레임・seed {v3}・{v4}・Steps {v5}・가이드는 짧은 변 {v6} 으로 읽습니다"},
    "Turbo なし": {"en": "no Turbo", "zh": "无 Turbo", "ko": "Turbo 없음"},
    "⏳ 生成中  {v0}/{v1} steps  ⏱ {v2}s": {"en": "⏳ Generating  {v0}/{v1} steps  ⏱ {v2}s", "zh": "⏳ 生成中  {v0}/{v1} steps  ⏱ {v2}s",
                                         "ko": "⏳ 생성 중  {v0}/{v1} steps  ⏱ {v2}s"},
    "❌ 生成に失敗しました: {v0}": {"en": "❌ Generation failed: {v0}", "zh": "❌ 生成失败：{v0}", "ko": "❌ 생성에 실패했습니다: {v0}"},
    "📼 書き出しています…": {"en": "📼 Writing the video…", "zh": "📼 正在写出视频…", "ko": "📼 영상을 쓰는 중…"},
    "❌ 動画を書き出せませんでした: {v0}": {"en": "❌ Could not write the video: {v0}", "zh": "❌ 无法写出视频：{v0}", "ko": "❌ 영상을 쓸 수 없었습니다: {v0}"},
    "✅ 生成しました（{v0} 秒）: {v1}": {"en": "✅ Generated ({v0} s): {v1}", "zh": "✅ 已生成（{v0} 秒）：{v1}", "ko": "✅ 생성했습니다({v0} 초): {v1}"},
    "停止": {"en": "Stop", "zh": "停止", "ko": "정지"},
}

_ST = {"ctx": None, "jobs": {}, "lock": threading.Lock()}
_UI = {}

JS_TEXT_KEYS = ("🖼 画像", "👤 画像から配置", "下敷き", "人を探しています…", "人を認識できませんでした", "画像に人が見つかりませんでした",
                "全体", "カメラ", "女性", "男性", "読み込み中…", "three.js を読み込めませんでした", "人体を読み込めませんでした",
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



# ------------------------------------------------------------------
#  0.2.0 生成（ガイド → R2V の <Video 1>）
# ------------------------------------------------------------------
def _where(x):
    """画面の横位置（−1〜1）→ 言葉"""
    return "on the left" if x < -0.12 else ("on the right" if x > 0.12 else "in the center")   # 二人が ±0.26 前後に立つ構図でも左右を言える幅


def _tone_word(v):
    return "very light grey" if v >= 0.8 else ("light grey" if v >= 0.62 else ("mid-grey" if v >= 0.5 else "dark grey"))


def _desc_of(name):
    """RefMod の見た目の説明があるか（refmod_tools の desc_get）"""
    try:
        rt = (_g().get("_MODS") or {}).get("refmod_tools")
        d = rt.desc_get(name) if rt is not None else {}
        return bool(str(d.get("appearance") or "").strip() or str(d.get("outfit") or "").strip())
    except Exception:                                             # noqa: BLE001
        return False


_FRAME_WORD = {"full": "a full shot showing them head to toe", "knee": "a medium-wide shot from the knees up",
               "waist": "a medium shot from the waist up", "chest": "a chest-up medium close-up", "face": "a close-up on the face",
               "wide": "a wide shot of the place"}
_TIME_RE = re.compile(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*s\s*:")


def _split_by_shots(act, shots):
    """時刻つきの文（"0-2s: …"）をショットへ振り分ける → [文, …]（ショットの数だけ）。時刻の無い頭の文は 1 つ目のショットへ"""
    out = [[] for _ in shots]
    pos = [(m.start(), float(m.group(1))) for m in _TIME_RE.finditer(act)]
    if not pos:
        if act:
            out[0].append(act)
        return [" ".join(x) for x in out]
    if act[:pos[0][0]].strip():
        out[0].append(act[:pos[0][0]].strip())
    for i, (st, t0) in enumerate(pos):
        en = pos[i + 1][0] if i + 1 < len(pos) else len(act)
        k = max([j for j, sh in enumerate(shots) if t0 >= float(sh["a"]) - 1e-6] or [0])
        out[k].append(act[st:en].strip())
    return [" ".join(x) for x in out]


def _shift_cut_times(text, src, dst):
    """動きの文の時刻のうち、カットの時刻（±0.05 秒）と同じものを前倒しした時刻に置き換える（ショットの頭の時刻と食い違わないように）"""
    def fix(v):
        x = float(v)
        for a, b in zip(src, dst):
            if abs(x - a) <= 0.05:
                return f"{b:.1f}"
        return v

    return _TIME_RE.sub(lambda m: f"{fix(m.group(1))}-{fix(m.group(2))}s:", text)


def compose_prompt(scene, rms, place, action):
    """シーン（書き出しの JSON）・人ごとの RefMod・場所・動きの文 → 6 節の R2V プロンプト（<RefMod N>・@character N は本体が展開）。
    動きの文が節の見出し（subject_definitions:）を持っていれば、利用者が書いた全文としてそのまま使う。
    0.4.0 カットがあれば detailed_description を [Shot N] に分け、各ショットの頭に時刻・構図・映っている人を書く（カットの時刻は CUT_LEAD 前倒し）"""
    act = str(action or "").strip()
    if re.search(r"^\s*subject_definitions\s*:", act, re.M):
        return act
    people = list(scene.get("people") or [])
    scr = scene.get("screen") or {}
    grays = list(scene.get("grays") or [])
    shots = list(scene.get("shots") or [])
    multi = len(shots) > 1
    place = str(place or "").strip() or "a natural, realistic location"
    defs, who, keep, pos = [], [], [], []
    shot_tags = ", ".join(f"[Shot {i + 1}]" for i in range(len(shots))) if multi else "[Shot 1]"
    for i, p in enumerate(people):
        n = i + 1
        rm = rms[i] if i < len(rms) else None
        if rm:
            defs.append(f"<Subject {n}> is the person in <RefMod {n}>" + (f": @character {n}." if _desc_of(rm) else "."))
        else:
            defs.append(f"<Subject {n}> is a {'man' if p.get('kind') == 'm' else 'woman'} with a natural, realistic look.")
        sc = scr.get(p.get("id")) or []
        w0 = _where(sc[0][0]) if sc else "in the frame"
        w1 = _where(sc[-1][0]) if len(sc) > 1 else w0
        tone = _tone_word(grays[i]) if i < len(grays) else "grey"
        who.append(f"<Subject {n}> is the {tone} mannequin {w0}")
        pos.append(f"<Subject {n}> stands {w0}" + (f" and ends {w1}" if (w1 != w0 and not multi) else ""))
        keep.append(f"<Subject {n}> (appears in {shot_tags}): partially_preserved - face and hair are kept; the pose and place "
                    f"follow the guide and the description.")
    if multi:
        cut_t = [max(0.1, float(sh["a"]) - CUT_LEAD) for sh in shots[1:]]
        guide = ("The camera, the framing and where each person stands in each shot come from <Video 1>, a simple grey mannequin guide "
                 "with the same hard cuts: each grey mannequin stands for one person. " + ("; ".join(who) + ". " if who else "")
                 + "The guide's grey look is not shown; the people and the place look real. Faces stay the same people in every shot.")
        summ = (f"{len(shots)} shots in {place}, joined by hard cuts at " + ", ".join(f"{c:.1f}s" for c in cut_t) + f". {guide}")
        parts_act = [_shift_cut_times(x, [float(sh["a"]) for sh in shots[1:]], cut_t) for x in _split_by_shots(act, shots)]
        lines = []
        for i, sh in enumerate(shots):
            a = 0.0 if i == 0 else cut_t[i - 1]
            b = cut_t[i] if i < len(cut_t) else float(sh["b"])
            vis = sorted(sh.get("who") or [], key=lambda q: q.get("x", 0))
            ppl = (", ".join(f"<Subject {q['n']}> {_where(q.get('x', 0))}" for q in vis) if vis else "no one in the frame")
            head = (f"[Shot {i + 1}] {a:.1f}-{b:.1f}s: " + ("hard cut to " if i > 0 else "")
                    + f"{_FRAME_WORD.get(sh.get('frame'), _FRAME_WORD['waist'])} — {ppl}.")
            body = parts_act[i] if i < len(parts_act) else ""
            lines.append((head + " " + body).strip() + " The camera follows the guide <Video 1> for this shot.")
        detailed = "Realistic photography with soft natural light, " + place + ".\n" + "\n".join(lines)
    else:
        guide = ("The camera movement, the framing and where each person stands and faces come from <Video 1>, a simple grey mannequin "
                 "guide: each grey mannequin stands for one person. " + ("; ".join(who) + ". " if who else "")
                 + "The guide's grey look is not shown; the people and the place look real. Faces stay the same people throughout.")
        summ = f"One continuous shot in {place}. {guide}"
        detailed = ("Realistic photography with soft natural light. [Shot 1] " + place[0].upper() + place[1:] + ". "
                    + (". ".join(pos) + ". " if pos else "") + (act + " " if act else "")
                    + "The camera follows exactly the movement of <Video 1>: its position, distance and direction change exactly as "
                    "the guide does.")
    sound = ("The voices of the people and the natural ambience of the place." if re.search(r"<d>|says|said|speaks|talks", act, re.I)
             else "The natural ambience of the place.")
    parts = [
        "subject_definitions:\n" + ("\n".join(defs) if defs else "N/A"),
        f"summary:\n[reference generation] {summ}",
        f"retention_analysis:\n<Video 1> (appears in {shot_tags}): weak_reference - only the camera motion, the framing"
        + (", the cuts" if multi else "") + " and the positions, sizes and facing of the mannequins are used; the mannequins are "
        "replaced by the real people.\n" + "\n".join(keep),
        "detailed_description:\n" + detailed,
        f"overall_soundscape:\n{sound}",
        "non_diegetic_music:\nN/A",
    ]
    return "\n\n".join(parts)


def _canvas(edge):
    """動画参照を読む大きさ（canvas_short_edge・canvas_max_pixels）を生成の間だけ変える（生成の大きさは width/height で決まる）"""
    import contextlib

    @contextlib.contextmanager
    def cm():
        pipe = _g()["pipe"]
        b0 = (int(getattr(pipe.config, "canvas_short_edge", 768)), int(getattr(pipe.config, "canvas_max_pixels", 768 * 1344)))
        try:
            pipe.register_to_config(canvas_short_edge=int(edge), canvas_max_pixels=int(edge * edge * 1344 / 768) + 1)
            yield
        finally:
            pipe.register_to_config(canvas_short_edge=b0[0], canvas_max_pixels=b0[1])
    return cm()


def c3d_generate(gpath, rms, place, action, seed, usekf=False, kfpath=""):
    """書き出したガイドで R2V を回す（ジェネレータ: (STATUS, 結果の動画)）"""
    import time
    import numpy as np
    from PIL import Image
    g = _g()
    gp = str(gpath or "")
    if not gp:
        yield _T("編集画面がまだ読み込まれていません（CAMERA 3D タブを開いてから押してください）"), None
        return
    if gp.startswith("ERR:") or not os.path.isfile(gp):
        yield _T("⚠️ 書き出せませんでした: {v0}", v0=gp[4:].strip() if gp.startswith("ERR:") else gp), None
        return
    try:
        with open(gp[:-4] + ".json", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception as e:                                        # noqa: BLE001
        yield _T("⚠️ 書き出せませんでした: {v0}", v0=f"{e}"), None
        return
    scene = meta.get("scene") or {}
    rms = [str(x) for x in (rms or []) if str(x).strip()]
    nf = int(meta.get("frames") or 0)
    lines = [_T("書き出しました: {v0}（{v1}×{v2}・{v3} コマ・{v4} 秒）", v0=os.path.basename(gp), v1=meta.get("w"), v2=meta.get("h"),
                v3=nf, v4=f"{nf / float(FPS):.2f}")]
    try:
        from diffusers.modular_pipelines.minimax_h3.modular_pipeline import resolve_canvas_size
        h, w = resolve_canvas_size(int(meta["w"]), int(meta["h"]), 32, 768, 768 * 1344)
    except Exception:                                             # noqa: BLE001
        w, h = (1344, 768) if int(meta.get("w", 16)) >= int(meta.get("h", 9)) else (768, 1344)
    n_people = len(scene.get("people") or [])
    if len(rms) < n_people:
        lines.append(_T("⚠️ RefMod が無い人は言葉だけで描きます（{v0} 人中 {v1} 人に RefMod）", v0=n_people, v1=len(rms)))
    for i, nm in enumerate(rms[:n_people]):
        if not _desc_of(nm):
            lines.append(_T("ℹ️ 人 {v0}（{v1}）は見た目の説明が無いのでラベルだけで指します（FINDER で説明を付けると似やすくなります）", v0=i + 1, v1=nm))
    rm = g["_REFMOD"]
    rm0 = {k: (list(v) if isinstance(v, list) else (dict(v) if isinstance(v, dict) else v))
           for k, v in rm.items() if k in ("sel", "strength", "each", "cap")}
    rvf0 = g["_UI_STATE"].get("ref_video_frames")
    sd = int(seed) if seed is not None and int(seed) >= 0 else int(np.random.randint(0, 2 ** 31 - 1))
    refs = {"image": [], "video": [gp], "audio": []}
    box = {}
    kfe = None
    if usekf:                                                     # 0.3.0 画像を 0 秒のキーフレームに（本体の R2V のキーフレーム）
        kp = str(kfpath or "")
        if not (kp and os.path.isfile(kp)):
            lines.append(_T("⚠️ 最初のコマにする画像がありません（編集画面の「🖼 画像」で読み込んでください）"))
        else:
            try:
                kfe, _kn, kerr = g["kf_prepare"]([{"path": kp, "sec": 0.0, "name": os.path.basename(kp)}], w, h, nf)
                if kfe:
                    lines.append(_T("🖼 画像を最初のコマにします（0 秒のキーフレーム）"))
                else:
                    lines.append(_T("⚠️ キーフレームを用意できませんでした: {v0}", v0=kerr or "?"))
            except Exception as e:                                # noqa: BLE001
                kfe = None
                lines.append(_T("⚠️ キーフレームを用意できませんでした: {v0}", v0=f"{e}"))
    try:
        ok, msg = g["ensure_mode"]("Ref2VA")
        if not ok:
            yield "\n".join(lines + ["❌ " + str(msg)]), None
            return
        rm.update(sel=list(rms[:max(1, n_people)]), strength=1.0, each={}, cap=0)
        g["_UI_STATE"]["ref_video_frames"] = 0
        prompt = compose_prompt(scene, rms, place, action)
        try:
            prompt, notes = g["expand_prompt_labels"](prompt, refs)
            lines += list(notes or [])
        except Exception as e:                                    # noqa: BLE001
            lines.append(_T("⚠️ ラベルを展開できませんでした: {v0}", v0=f"{e}"))
        key = g["turbo_key"]()
        try:
            steps = int(g["steps_for_lora"](key, False, "Ref2VA") or 0) or 4
        except Exception:                                         # noqa: BLE001
            steps = 4
        lines.append(_T("🎬 R2V: {v0}×{v1}・{v2} コマ・seed {v3}・{v4}・Steps {v5}・ガイドは短辺 {v6} で読みます",
                        v0=w, v1=h, v2=nf, v3=sd, v4=key or _T("Turbo なし"), v5=steps, v6=GUIDE_READ_EDGE))
        prog = {"n": 0, "total": steps, "phase": "denoise"}

        def _worker():
            try:
                with _canvas(GUIDE_READ_EDGE):
                    box["res"] = g["_run_pipe"]("Ref2VA", prompt, w, h, nf, steps, sd, None, None, refs, prog, kf_entries=kfe)
            except BaseException as e:                            # noqa: BLE001
                box["err"] = e
        th = threading.Thread(target=_worker, daemon=True)
        t0 = time.time()
        th.start()
        while th.is_alive():
            yield "\n".join(lines + [_T("⏳ 生成中  {v0}/{v1} steps  ⏱ {v2}s", v0=prog.get("n", 0), v1=prog.get("total", steps),
                                        v2=f"{time.time() - t0:.0f}")]), None
            time.sleep(0.5)
        th.join()
    finally:
        g["_UI_STATE"]["ref_video_frames"] = rvf0
        try:
            rm.update(rm0)
        except Exception:                                         # noqa: BLE001
            pass
    if "err" in box:
        try:
            g["_free_vram"]()
        except Exception:                                         # noqa: BLE001
            pass
        e = box["err"]
        yield "\n".join(lines + [_T("❌ 生成に失敗しました: {v0}", v0=f"{type(e).__name__}: {e}")]), None
        return
    r = box["res"]
    yield "\n".join(lines + [_T("📼 書き出しています…")]), None
    try:
        def _px(f):                                               # PIL・uint8・0〜1 の小数のどれでも RGB の PIL に
            if isinstance(f, Image.Image):
                return f.convert("RGB")
            a = np.asarray(f)
            if a.dtype != np.uint8:
                a = np.clip(a * (255.0 if float(a.max(initial=0)) <= 1.0 + 1e-6 else 1.0), 0, 255).round().astype(np.uint8)
            return Image.fromarray(a)
        frames = [_px(f) for f in r["frames"]]
        stamp = datetime.datetime.now().strftime("%H%M%S")
        out = os.path.join("/content", f"minimax_h3_c3d_{stamp}_{sd}.mp4")
        g["export_to_video"](frames, out, fps=FPS)
    except Exception as e:                                        # noqa: BLE001
        yield "\n".join(lines + [_T("❌ 動画を書き出せませんでした: {v0}", v0=f"{type(e).__name__}: {e}")]), None
        return
    if r.get("audio") is not None:
        try:
            g["_mux_audio"](out, r["audio"], r.get("sr"))         # 本体の生成と同じ渡し方
        except Exception as e:                                    # noqa: BLE001
            lines.append(f"⚠️ audio: {e}")
    try:
        m = g["build_meta"]("Ref2VA", prompt, w, h, "", nf / float(FPS), nf, steps, sd, key,
                            float(g["_LORA_STATE"].get("strength", 1.0)), refs, float(r.get("sec", 0.0)), float(r.get("peak", 0.0)))
        m["camera3d"] = {"guide": gp, "read_edge": GUIDE_READ_EDGE, "first_frame": (str(kfpath) if kfe else ""),
                         "module": f"{NAME} {VERSION}"}
        m["refmods"] = {"names": rms[:max(1, n_people)], "strength": 1.0, "each": {n: 1.0 for n in rms[:max(1, n_people)]}, "cap": 0}
        g["write_meta"](out, m)
    except Exception as e:                                        # noqa: BLE001
        lines.append(f"⚠️ meta: {e}")
    lines.append(_T("✅ 生成しました（{v0} 秒）: {v1}", v0=f"{float(r.get('sec', 0.0)):.0f}", v1=os.path.basename(out)))
    yield "\n".join(lines), out


def _refmod_choices():
    try:
        return list(_g()["refmod_choices"]())
    except Exception:                                             # noqa: BLE001
        return []


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
    <img class="c3d-bg" alt="">
    <div class="c3d-labels"></div>
    <div class="c3d-bar">
      <button type="button" class="c3d-btn c3d-v-edit" data-view="edit"></button>
      <button type="button" class="c3d-btn c3d-v-cam" data-view="cam"></button>
      <span class="c3d-sep"></span>
      <button type="button" class="c3d-btn c3d-img"></button>
      <button type="button" class="c3d-btn c3d-bgop"></button>
      <button type="button" class="c3d-btn c3d-fit"></button>
      <input type="file" class="c3d-file" accept="image/*" hidden>
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
  host.querySelector('.c3d-img').textContent = tx('🖼 画像');
  host.querySelector('.c3d-fit').textContent = tx('👤 画像から配置');
  if (S) paintBgBtn();
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
  const rt = { wrap, model, bones, rest, mat, pick, footY, label, pose: null, kind: p.kind };
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
// 0.4.0 ショット（カットで割った区間）。カメラはショットの中のキーだけで補間する（カットをまたがない）
function cutsOf() { return (S.cuts || []).filter((c) => c > 0 && c < S.dur).sort((a, b) => a - b); }
function shotRange(t) {
  const cs = cutsOf(); let a = 0, b = S.dur;
  for (const c of cs) { if (c <= t + 1e-6) a = c; else { b = c; break; } }
  return [a, b];
}
function camKeysV(t) {
  let keys = S.cam.keys;
  if (t !== undefined && (S.cuts || []).length) {
    const [a, b] = shotRange(t);
    const inShot = keys.filter((k) => k.t >= a - 1e-6 && k.t < b - 1e-6);
    if (inShot.length) keys = inShot;
    else { const before = keys.filter((k) => k.t < a - 1e-6); keys = before.length ? [before[before.length - 1]] : []; }
  }
  let prev = null;
  return keys.map((k) => { const v = camVec(k); if (prev) v[4] = unwrap(v[4], prev[4]); prev = v; return { t: k.t, v }; });
}
function personKeysV(p) {
  let prev = null;
  return p.keys.map((k) => { const v = [k.x, k.z, k.ry]; if (prev) v[2] = unwrap(v[2], prev[2]); prev = v; return { t: k.t, v }; });
}
function camAt(t) { const v = sample(camKeysV(t), t, S.ease); return v ? camFromVec(v) : { pos: S.cam.pos, tgt: S.cam.tgt, lens: S.cam.lens }; }
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
  shot.updateMatrixWorld(true);              // 0.4.0 測るとき（描く前）に古い行列で投影しないように
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
  host.querySelectorAll('.c3d-bar .c3d-btn[data-view]').forEach((b) => b.classList.toggle('c3d-on', b.dataset.view === S.view));
  attachGizmo(); save(); dirty = true; placeBg();
}
host.querySelectorAll('.c3d-bar .c3d-btn[data-view]').forEach((b) => b.addEventListener('click', () => setView(b.dataset.view)));
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
  placeBg(vp);
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
  const cs = cutsOf();
  if (cs.length) {                          // 0.4.0 カットの線（全部の段をまたぐ）とショットの番号
    const lay = document.createElement('div'); lay.className = 'c3d-cuts';
    [0].concat(cs).forEach((c, i) => {
      if (i > 0) { const l = document.createElement('div'); l.className = 'c3d-cut'; l.style.left = (c / S.dur * 100) + '%'; l.title = '✂ ' + c.toFixed(2) + ' s'; lay.appendChild(l); }
      const lb = document.createElement('b'); lb.className = 'c3d-shot'; lb.textContent = 'S' + (i + 1);
      lb.style.left = (c / S.dur * 100) + '%'; lay.appendChild(lb);
    });
    rowsEl.appendChild(lay);
  }
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

// ---------------- 0.3.0 画像の下敷きと、画像から配置 ----------------
const bgEl = host.querySelector('.c3d-bg'), fileEl = host.querySelector('.c3d-file');
const BG_OPS = [0, 0.35, 0.65];
let bgFull = null;                         // 認識に使う元の大きさの画像（保存しない）
function paintBgBtn() {
  const b = host.querySelector('.c3d-bgop');
  b.textContent = tx('下敷き') + ' ' + Math.round((S.bgOp || 0) * 100) + '%';
  b.style.display = S.bg ? '' : 'none';
  host.querySelector('.c3d-fit').style.display = S.bg ? '' : 'none';
}
function placeBg(vp) {
  if (!S.bg || S.view !== 'cam' || !(S.bgOp > 0)) { bgEl.style.display = 'none'; return; }
  vp = vp || viewRect();
  if (bgEl.getAttribute('src') !== S.bg) bgEl.src = S.bg;
  Object.assign(bgEl.style, { display: 'block', left: vp.x + 'px', top: vp.y + 'px', width: vp.w + 'px', height: vp.h + 'px',
    opacity: String(S.bgOp) });
}
function nearestAspect(w, h) {
  let best = '16:9', d = 1e9;
  for (const [k, a] of Object.entries(ASPECTS)) { const e = Math.abs(Math.log((w / h) / (a[0] / a[1]))); if (e < d) { d = e; best = k; } }
  return best;
}
host.querySelector('.c3d-img').addEventListener('click', () => fileEl.click());
host.querySelector('.c3d-bgop').addEventListener('click', () => {
  const i = BG_OPS.indexOf(S.bgOp); S.bgOp = BG_OPS[(i + 1) % BG_OPS.length]; paintBgBtn(); placeBg(); save();
});
fileEl.addEventListener('change', async () => {
  const f = fileEl.files && fileEl.files[0]; if (!f) return;
  fileEl.value = '';
  const url = await new Promise((ok, ng) => { const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = ng; r.readAsDataURL(f); });
  const im = new Image(); im.src = url; await im.decode();
  bgFull = im;
  // 下敷きは長い辺 960 の JPEG にしてブラウザに控える（再読み込みでも残す）。元の画像はサーバへ（最初のコマに使うとき）
  const k = Math.min(1, 960 / Math.max(im.width, im.height));
  const cv = document.createElement('canvas'); cv.width = Math.round(im.width * k); cv.height = Math.round(im.height * k);
  cv.getContext('2d').drawImage(im, 0, 0, cv.width, cv.height);
  S.bg = cv.toDataURL('image/jpeg', 0.85); S.bgW = im.width; S.bgH = im.height;
  if (!(S.bgOp > 0)) S.bgOp = 0.35;
  S.bgPath = '';
  try { const u = await upload(f); S.bgPath = (u && u.path) || ''; } catch (e) { console.warn(e); }
  api.set({ aspect: nearestAspect(im.width, im.height) });
  setView('cam'); paintBgBtn(); placeBg(); save(); bridge();
});
let poser = null;
async function getPoser() {
  if (poser) return poser;
  const V = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@__MP_VER__';
  const mp = await import(V + '/vision_bundle.mjs');
  const fs = await mp.FilesetResolver.forVisionTasks(V + '/wasm');
  poser = await mp.PoseLandmarker.createFromOptions(fs, { baseOptions: { modelAssetPath: '__MP_MODEL__', delegate: 'CPU' },
    runningMode: 'IMAGE', numPoses: 6 });
  return poser;
}
const mid = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, z: (a.z + b.z) / 2 });
const toCam = (p) => new THREE.Vector3(p.x, -p.y, -p.z);         // MediaPipe の世界座標（x 右・y 下・z 奥）→ カメラ座標（y 上・z 手前）
function ang(a, b, c) {                    // b の角（度）
  const u = new THREE.Vector3(a.x - b.x, a.y - b.y, a.z - b.z), v = new THREE.Vector3(c.x - b.x, c.y - b.y, c.z - b.z);
  return u.angleTo(v) * 180 / Math.PI;
}
function poseOf(w, L) {
  const knee = Math.min(ang(w[23], w[25], w[27]), ang(w[24], w[26], w[28]));
  const hip = Math.min(ang(w[11], w[23], w[25]), ang(w[12], w[24], w[26]));
  if (hip < 130 && knee < 140) return 'sit';
  if (L[15].y < L[11].y || L[16].y < L[12].y) return 'raise';
  const stride = Math.hypot(w[27].x - w[28].x, w[27].z - w[28].z);
  if (stride > 0.32) return 'walk';
  return 'stand';
}
async function fitFromImage() {
  if (!bgFull) {                            // 再読み込み後は控えの下敷きで認識する
    if (!S.bg) return;
    const im = new Image(); im.src = S.bg; await im.decode(); bgFull = im;
  }
  say(tx('人を探しています…'));
  let res;
  try { res = (await getPoser()).detect(bgFull); } catch (e) { say(tx('人を認識できませんでした') + ': ' + e); return; }
  const n = (res.landmarks || []).length;
  if (!n) { say(tx('画像に人が見つかりませんでした')); setTimeout(() => say(''), 2500); return; }
  const W = bgFull.naturalWidth || bgFull.width, H = bgFull.naturalHeight || bgFull.height;
  const lens = camAt(S.t).lens || 35;
  const fpx = (W >= H ? W : H) * lens / 36;  // three の filmGauge 36 は長い辺
  // 人ごとにカメラ座標の腰の位置・胴の向き（上）・体の向き
  const P = [];
  for (let i = 0; i < n; i++) {
    const L = res.landmarks[i], w = res.worldLandmarks[i];
    const sh2 = mid(L[11], L[12]), hp2 = mid(L[23], L[24]);
    const lpx = Math.hypot((sh2.x - hp2.x) * W, (sh2.y - hp2.y) * H);
    const sw = mid(w[11], w[12]), hw = mid(w[23], w[24]);
    const lm = Math.hypot(sw.x - hw.x, sw.y - hw.y, sw.z - hw.z);
    if (!(lpx > 4) || !(lm > 0.05)) continue;
    const Z = fpx * lm / lpx;
    const hipC = new THREE.Vector3((hp2.x * W - W / 2) * Z / fpx, -(hp2.y * H - H / 2) * Z / fpx, -Z);
    const up = toCam({ x: sw.x - hw.x, y: sw.y - hw.y, z: sw.z - hw.z }).normalize();
    const s = { x: w[11].x - w[12].x, y: w[11].y - w[12].y, z: w[11].z - w[12].z };     // 右肩 → 左肩
    const fwd = toCam({ x: s.z, y: 0, z: -s.x });                                       // 肩 × 上（MediaPipe の座標で）→ 体の前
    const pose = poseOf(w, L);
    P.push({ hipC, up, fwd, pose, sx: hp2.x });
  }
  if (!P.length) { say(tx('画像に人が見つかりませんでした')); setTimeout(() => say(''), 2500); return; }
  P.sort((a, b) => a.sx - b.sx);           // 画面の左から（人の番号＝<Subject N> の順）
  // カメラの俯き（胴の上向きの平均から）と高さ（腰の高さから）
  const upm = new THREE.Vector3(); P.forEach((q) => upm.add(q.up)); upm.normalize();
  let th = Math.atan2(upm.z, upm.y);
  th = Math.max(-0.5, Math.min(0.8, th));
  const upC = new THREE.Vector3(0, Math.cos(th), Math.sin(th));
  const rot = (v) => new THREE.Vector3(v.x, v.y * Math.cos(th) + v.z * Math.sin(th), -v.y * Math.sin(th) + v.z * Math.cos(th));
  let hc = 0; P.forEach((q) => { hc += (q.pose === 'sit' ? 0.5 : 0.92) - q.hipC.dot(upC); }); hc /= P.length;
  hc = Math.max(0.2, Math.min(6, hc));
  const wp = P.map((q) => rot(q.hipC));
  const cz = wp.reduce((a, v) => a + v.z, 0) / wp.length, cx = wp.reduce((a, v) => a + v.x, 0) / wp.length;
  const camPos = new THREE.Vector3(-cx, hc, -cz);
  const dist = Math.max(0.5, -cz);
  const tgt = camPos.clone().add(new THREE.Vector3(0, -Math.sin(th), -Math.cos(th)).multiplyScalar(dist));
  // 人数を合わせる（左から順に、今の人の種類を引き継ぐ）
  const old = S.people.slice().sort((a, b) => personAt(a, S.t).x - personAt(b, S.t).x);
  while (S.people.length > P.length) { const p = S.people.pop(); despawn(p.id); }
  const kinds = old.map((p) => p.kind);
  while (S.people.length < P.length) {
    const p = { id: 'p' + Date.now().toString(36) + S.people.length, kind: 'f', pose: 'stand', x: 0, z: 0, ry: 0, keys: [] };
    S.people.push(p); await spawn(p);
  }
  S.people.forEach((p, i) => {
    const q = P[i], v = wp[i], f = rot(q.fwd);
    p.kind = kinds[i] || p.kind;
    p.pose = q.pose;
    const val = { x: v.x - cx, z: v.z - cz, ry: Math.atan2(f.x, f.z) };
    if (p.keys.length) setKey(p.keys, S.t, val); else Object.assign(p, val);
    const rt = RT.get(p.id); if (rt) rt.pose = null;
  });
  // 種類（女性／男性）が変わった人は作り直す
  for (const p of S.people) {
    const rt = RT.get(p.id);
    if (rt && rt.kind !== p.kind) { despawn(p.id); await spawn(p); }
  }
  const c = { pos: camPos.toArray(), tgt: tgt.toArray(), lens };
  if (S.cam.keys.length) setKey(S.cam.keys, S.t, c); else Object.assign(S.cam, c);
  S.bgOp = S.bgOp > 0 ? S.bgOp : 0.35;
  say(''); setView('cam'); select('cam'); buildRows(); setTime(S.t); paintBgBtn();
}
host.querySelector('.c3d-fit').addEventListener('click', () => { fitFromImage().catch((e) => say(String(e))); });

const api = {
  set(o) {
    o = o || {};
    if ('dur' in o) { S.dur = Math.max(1, Math.min(15, +o.dur || 5)); S.t = Math.min(S.t, S.dur); S.cuts = (S.cuts || []).filter((c) => c < S.dur); }
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
  addCut() {                                // 再生位置でショットを割る
    const t = snapT(S.t);
    if (t <= 1 / FPS || t >= S.dur - 1 / FPS) return;
    S.cuts = S.cuts || [];
    if (S.cuts.some((c) => Math.abs(c - t) < KEY_EPS)) return;
    // 前のショットの動きを保つ（カットの 1 コマ前にキー）＋新しいショットはカットの時刻のカメラから
    const before = camAt(t - 1 / FPS), at = camAt(t);
    S.cuts.push(t); S.cuts.sort((a, b) => a - b);
    if (S.cam.keys.length) {
      setKey(S.cam.keys, t - 1 / FPS, before);
      setKey(S.cam.keys, t, at);
    } else {
      setKey(S.cam.keys, 0, { pos: S.cam.pos, tgt: S.cam.tgt, lens: S.cam.lens });
      setKey(S.cam.keys, t, at);
    }
    select('cam'); buildRows(); setTime(t);
  },
  removeCut() {                             // 再生位置にいちばん近いカットを消す（1 秒以内）
    const cs = S.cuts || []; if (!cs.length) return;
    let bi = -1, bd = 1.0;
    cs.forEach((c, i) => { const d = Math.abs(c - S.t); if (d < bd) { bd = d; bi = i; } });
    if (bi >= 0) { cs.splice(bi, 1); buildRows(); setTime(S.t); }
  },
  bgPath() { return S.bgPath || ''; },
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
    // 0.2.0 人の頭が画面のどこにあるか（最初と最後のコマ）。プロンプトの「左の人」などに使う
    // 0.4.0 ショットごとに真ん中のコマで構図（どこまで映るか）と映っている人も測る
    const keepAspect0 = shotAspect; shotAspect = W / H;
    const screen = {};
    const proj = (b) => { const v = new THREE.Vector3(); b.getWorldPosition(v); v.project(shot); return v; };
    const inF = (v) => v.z < 1 && Math.abs(v.x) <= 1 && Math.abs(v.y) <= 1;
    for (const tt of [0, S.dur]) {
      applyTime(tt);
      S.people.forEach((p) => {
        const rt = RT.get(p.id); if (!rt) return;
        const v = proj(rt.bones.Head || rt.wrap);
        (screen[p.id] = screen[p.id] || []).push([+v.x.toFixed(3), +v.y.toFixed(3), inF(v)]);
      });
    }
    const bounds = [0].concat(cutsOf(), [S.dur]);
    const shots = [];
    for (let i = 0; i + 1 < bounds.length; i++) {
      const a = bounds[i], b = bounds[i + 1];
      applyTime((a + b) / 2);
      const who = [];
      let frame = 'wide';
      const order = ['face', 'chest', 'waist', 'knee', 'full'];
      S.people.forEach((p, k) => {
        const rt = RT.get(p.id); if (!rt) return;
        const B = rt.bones, h = B.Head ? proj(B.Head) : null;
        if (!h || !inF(h)) return;
        const lo = (n) => (B[n] ? proj(B[n]).y >= -1 : false);   // その骨が画面の下の端より上にあるか
        const f = (B.ball_l && lo('ball_l')) ? 'full' : (B.calf_l && lo('calf_l')) ? 'knee' : (B.pelvis && lo('pelvis')) ? 'waist'
          : (B.spine_03 && lo('spine_03')) ? 'chest' : 'face';
        who.push({ n: k + 1, x: +h.x.toFixed(3), frame: f });
        if (frame === 'wide' || order.indexOf(f) < order.indexOf(frame)) frame = f;   // いちばん寄っている人に合わせる
      });
      shots.push({ a: +a.toFixed(3), b: +b.toFixed(3), frame, who });
    }
    shotAspect = keepAspect0;
    const sc0 = serialize(); sc0.screen = screen; sc0.grays = S.people.map((p, i) => grayOf(i)); sc0.shots = shots;
    const job = await server.c3d_begin({ w: W, h: H, n, scene: sc0 });
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
setView(S.view); select(S.sel); setTime(S.t); paintBgBtn();
host.dataset.ready = '1';
requestAnimationFrame(loop);
})();
"""


def _js():
    return (JS_ON_LOAD.replace("__THREE_VER__", THREE_VER).replace("__GUIDE_SHORT__", str(int(GUIDE_SHORT)))
            .replace("__MAX_FRAMES__", str(int(MAX_FRAMES))).replace("__MP_VER__", MP_VER).replace("__MP_MODEL__", MP_MODEL))


# 書き出しボタン: JS で描いて送り、できた mp4 のパスを Python へ渡す
EXPORT_JS = """
async (x) => {
  try {
    if (!window.__c3d) return '';
    return await window.__c3d.exportGuide();
  } catch (e) { return 'ERR: ' + (e && e.message ? e.message : e); }
}
"""


# 0.2.0 生成ボタン: 先にガイドを書き出し、そのパスと入力を Python へ
GEN_JS = """
async (x, rms, place, action, seed, usekf, kf) => {
  const bg = window.__c3d ? window.__c3d.bgPath() : '';
  try {
    if (!window.__c3d) return ['', rms, place, action, seed, usekf, bg];
    return [await window.__c3d.exportGuide(), rms, place, action, seed, usekf, bg];
  } catch (e) { return ['ERR: ' + (e && e.message ? e.message : e), rms, place, action, seed, usekf, bg]; }
}
"""


def _call_js(expr):
    return "(...a) => { try { if (window.__c3d) { " + expr + " } } catch (e) { console.error(e); } return a.length > 1 ? a : a[0]; }"


# ------------------------------------------------------------------
#  書式（本体の SEGMENTS の箱を写す＋編集画面の中身）
# ------------------------------------------------------------------
_MIRROR = {                                                       # SEGMENTS の id → CAMERA 3D の id
    "#seg-left": ["#c3d-left"], "#seg-right": ["#c3d-right"],
    "#seg-preview-box": ["#c3d-view-box", "#c3d-out-box", "#c3d-res-box"],
    "#seg-act": ["#c3d-scene", "#c3d-obj", "#c3d-gen"],
    "#seg-concat-btn": ["#c3d-add-f", "#c3d-add-m", "#c3d-del", "#c3d-key", "#c3d-unkey", "#c3d-export", "#c3d-run-btn",
                        "#c3d-cut", "#c3d-uncut"],
    "#seg-len": ["#c3d-dur", "#c3d-lens"],
    "#status-panel": ["#c3d-status"], "#lora-dd": ["#c3d-aspect", "#c3d-ease", "#c3d-pose", "#c3d-mode"],
    "#seg-note": ["#c3d-note"],
    "#seg-reseed": ["#c3d-usekf"],                                # 0.3.0 チェック（RETAKE の #rt-inherit と同じ写し）
}
CSS = ""
CSS_EXTRA = """
#c3d-bridge, #c3d-res, #c3d-kf { display: none !important; }
#c3d-left { justify-content: flex-start !important; }
#c3d-left > * { flex: 0 0 auto !important; }
#c3d-scene > *, #c3d-obj > *, #c3d-gen > * { margin-top: 0 !important; }
/* 0.2.0 文字の欄（場所・動き・Seed・RefMod）の見出しは（左の生成の箱は、見えている枠〔中の .form〕が編集画面の枠と左右の端でそろうように 12px）、同じ箱の部品（スライダー＝SEGMENT の写し）と同じ書式（RETAKE の #rt-action と同じ値） */
#c3d-place label, #c3d-place label > span:first-child, #c3d-action label, #c3d-action label > span:first-child,
#c3d-seed label, #c3d-seed label > span:first-child, #c3d-rms [data-testid="block-info"] {
    font-size: 12px !important; color: var(--h3-muted) !important; letter-spacing: 0.04em !important; font-weight: 400 !important;
}
#c3d-place textarea, #c3d-place input, #c3d-action textarea, #c3d-seed input { color: var(--h3-text3) !important; font-size: 13px !important; letter-spacing: 0 !important; }
#c3d-gen { margin-left: 12px !important; margin-right: 12px !important; width: calc(100% - 24px) !important; min-width: 0 !important; flex-grow: 0 !important; }
#c3d-status { margin-left: 12px !important; margin-right: 12px !important; width: calc(100% - 24px) !important; min-width: 0 !important; flex-grow: 0 !important; }
#c3d-btns, #c3d-keys, #c3d-cutrow { gap: 8px !important; flex-wrap: nowrap !important; }
#c3d-btns > *, #c3d-keys > *, #c3d-cutrow > * { min-width: 0 !important; }
#c3d-view-box { padding-top: 10px !important; }
/* 編集画面（three.js）。枠と角は Keyframe のプレビューとタイムライン（#kf-preview・#kf-list）に合わせる */
#c3d-editor .c3d-root { display: flex; flex-direction: column; gap: 8px; }
#c3d-editor .c3d-view { position: relative; width: 100%; aspect-ratio: 16 / 10; max-height: 440px; border: 1px solid var(--h3-border); border-radius: 10px;
    overflow: hidden; background: #161618; outline: none; }
#c3d-editor .c3d-canvas { display: block; width: 100%; height: 100%; touch-action: none; }
#c3d-editor .c3d-bar { position: absolute; top: 8px; left: 8px; right: 8px; display: flex; flex-wrap: wrap; gap: 6px; }
#c3d-editor .c3d-btn { height: 26px; padding: 0 10px; border-radius: 6px; border: 1px solid var(--h3-border2);
    background: var(--h3-icon-btn); color: var(--h3-muted); font-size: 11px; letter-spacing: 0.04em; cursor: pointer; }
#c3d-editor .c3d-btn:hover { background: var(--h3-elev); border-color: var(--h3-border-hover); color: var(--h3-text); }
#c3d-editor .c3d-btn.c3d-on { border-color: var(--h3-accent); color: var(--h3-accent-text); }
#c3d-editor .c3d-bg { display: none; position: absolute; pointer-events: none; object-fit: fill; }
#c3d-editor .c3d-sep { width: 6px; }
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
#c3d-editor .c3d-cuts { position: absolute; inset: 0; pointer-events: none; }
#c3d-editor .c3d-cut { position: absolute; top: 0; bottom: 0; width: 0; border-left: 2px solid var(--h3-danger-bg); margin-left: -1px; }
/* ショットの番号は下の端（上の端は秒の目盛りの数字） */
#c3d-editor .c3d-shot { position: absolute; bottom: 2px; margin-left: 4px; font-weight: 400; font-size: 10px; color: var(--h3-danger-text); }
#c3d-editor .c3d-tl-head-line { position: absolute; top: 0; bottom: 0; width: 0; border-left: 2px solid var(--h3-accent);
    margin-left: -1px; pointer-events: none; }
"""

HELP_C3D = ("3D の場に人（マネキン）とカメラを置き、時刻ごとの立ち位置・向き・カメラの位置をキーフレームで決めて、灰色のガイド動画を書き出します。"
            "ガイドを R2V の動画参照にすると、人物の位置・姿勢・構図・カメラの動きがガイドに付いてきます（セル196・197）。\n"
            "人は「＋ 女性」「＋ 男性」で足し、画面で押して選びます。「全体」の表示では矢印で動かし（操作＝回転で向きを変える）、"
            "「カメラ」の表示ではドラッグで回り込み・右ドラッグで平行移動・ホイールで寄り引きします。"
            "時刻を動かしてから人やカメラを動かすと、その時刻にキーが入ります（キーが 1 つも無いものは止まったまま）。\n"
            "動き（演技）はここでは付けず、生成のプロンプトに書きます。ガイドは 24fps・17n＋5 コマ・短辺 480 で /content/camera3d/ に書き出します"
            "（シーンの JSON も同じ名前で横に置きます）。\n"
            "「🎬 生成」はガイドを書き出して R2V に <Video 1> として渡します（短辺 256 で読むので速く、ガイドに忠実）。"
            "人物の RefMod は人の番号の順に選びます（1 人目→<Subject 1>）。見た目の説明がある RefMod は説明も入ります。"
            "場所と、時刻つきの動き・セリフを書けば、人の立ち位置（画面の左・中央・右）を足して 6 節のプロンプトを組みます。"
            "動きの欄に subject_definitions: から始まる全文を書けば、そのまま使います。Turbo・Steps は CREATE の今の設定です。\n"
            "「🖼 画像」でキーフレームの画像を読むと、カメラの表示に下敷きとして重なります（「下敷き」で濃さを切り替え）。"
            "「👤 画像から配置」は画像の人を認識して、人数・立ち位置・向き・姿勢とカメラの位置・高さ・俯きを今の時刻に置きます（おおまかなので下敷きを見て仕上げます）。"
            "生成の「画像を最初のコマにする」を ON にすると、その画像から始まります。\n"
            "「✂ カット」は再生位置でショットを割ります（カメラはカットをまたいで動かず、新しいショットはカットの時刻のカメラから始まる。人の立ち位置は続く）。"
            "生成では動き・セリフの時刻つきの文をカットの時刻で [Shot N] に分け、各ショットの構図（全身・膝上・胸上など）を足してハードカットにします")

I18N.update({
    HELP_C3D: {
        "en": "Place people (mannequins) and a camera in 3D, set where they stand, which way they face and where the camera is at each time "
              "with keyframes, and export a gray guide video. Used as the R2V video reference, the guide drives the people's positions, poses, "
              "framing and camera move (cells 196–197).\n"
              "Add people with “＋ Woman” / “＋ Man” and click one in the view to select it. In the “Scene” view drag the arrows "
              "(Gizmo = Rotate turns them); in the “Camera” view drag to orbit, right-drag to pan and use the wheel to dolly. "
              "Move the playhead first, then move a person or the camera to set a key at that time (anything with no keys stays still).\n"
              "Acting is not animated here — write it in the generation prompt. Guides are exported at 24 fps, 17n+5 frames, short side 480, "
              "to /content/camera3d/ (with the scene JSON next to them).\n“🎬 Generate” exports the guide and passes it to R2V as <Video 1> (read at short side 256: faster and more faithful to the guide). Pick the people's RefMods in person order (person 1 → <Subject 1>); RefMods with an appearance description bring it along. Write the place and the timed actions / lines, and the six-section prompt is composed with each person's position (left / center / right of the frame). A full prompt starting with subject_definitions: in the action box is used as is. Turbo and Steps follow the current CREATE settings. \n“🖼 Image” loads a keyframe image as an overlay in the Camera view (“Overlay” changes its opacity). “👤 Place from image” detects the people in it and sets the number of people, their positions, facing and poses and the camera position, height and tilt at the current time (rough — finish it against the overlay). Turn on “Use the image as the first frame” to start the generation from that image. \n“✂ Cut” splits the shot at the playhead (the camera does not move across a cut; a new shot starts from the camera at the cut time; people keep their positions). When generating, the timed actions / lines are split into [Shot N] at the cut times, each shot gets its framing (full, knees-up, chest-up…) and the shots are joined by hard cuts.",
        "zh": "在 3D 场景中放置人物（人体模型）和摄像机，用关键帧决定每个时刻的站位、朝向和摄像机位置，并导出灰色的引导视频。"
              "把引导视频作为 R2V 的视频参考，人物的位置、姿势、构图和摄像机运动会跟随引导（单元 196・197）。\n"
              "用「＋ 女性」「＋ 男性」添加人物，在画面中点击选择。在「全景」视图中拖动箭头移动（操作＝旋转可改变朝向），"
              "在「摄像机」视图中拖动环绕、右键拖动平移、滚轮推拉。先移动时间，再移动人物或摄像机，就会在该时刻设置关键帧（没有关键帧的对象保持不动）。\n"
              "动作（表演）不在这里制作，请写在生成的提示词里。引导视频以 24fps・17n+5 帧・短边 480 导出到 /content/camera3d/（同名的场景 JSON 放在旁边）。\n「🎬 生成」会导出引导视频并作为 <Video 1> 交给 R2V（以短边 256 读取，更快且更忠实于引导）。人物的 RefMod 按人物编号顺序选择（第 1 人→<Subject 1>）；带外貌描述的 RefMod 会一并加入。写上地点和带时间的动作・台词，就会加上每个人的站位（画面左・中・右）组成 6 节提示词。动作栏写以 subject_definitions: 开头的完整提示词时直接使用。Turbo・Steps 使用 CREATE 当前的设置。\n「🖼 图像」读取关键帧图像，在摄像机视图中作为底图叠加（「底图」切换浓淡）。「👤 按图像摆放」识别图中的人物，在当前时刻设置人数・站位・朝向・姿势以及摄像机的位置・高度・俯角（比较粗略，请对照底图调整）。打开「把图像作为第一帧」后，生成会从该图像开始。\n「✂ 剪切」在播放位置切分镜头（摄像机不会跨剪切移动，新镜头从剪切时刻的摄像机开始；人物站位延续）。生成时会把带时间的动作・台词按剪切时刻分成 [Shot N]，为每个镜头加上构图（全身・膝上・胸上等），并以硬切连接。",
        "ko": "3D 공간에 인물(마네킹)과 카메라를 놓고, 시간마다 서는 위치·방향·카메라 위치를 키프레임으로 정해 회색 가이드 영상을 내보냅니다. "
              "가이드를 R2V 의 영상 참조로 쓰면 인물의 위치·자세·구도·카메라 움직임이 가이드를 따라옵니다(셀 196・197).\n"
              "「＋ 여성」「＋ 남성」으로 인물을 추가하고 화면에서 눌러 선택합니다. 「전체」 보기에서는 화살표로 움직이고(조작＝회전으로 방향 변경), "
              "「카메라」 보기에서는 드래그로 돌아가기·오른쪽 드래그로 평행 이동·휠로 다가가기/물러나기를 합니다. "
              "시간을 먼저 옮긴 뒤 인물이나 카메라를 움직이면 그 시간에 키가 들어갑니다(키가 하나도 없는 것은 멈춘 채로).\n"
              "움직임(연기)은 여기서 만들지 않고 생성 프롬프트에 씁니다. 가이드는 24fps・17n+5 프레임・짧은 변 480 으로 /content/camera3d/ 에 내보냅니다"
              "(같은 이름의 장면 JSON 도 옆에 둡니다).\n「🎬 생성」은 가이드를 내보내 R2V 에 <Video 1> 로 넘깁니다(짧은 변 256 으로 읽어 빠르고 가이드에 충실). 인물의 RefMod 는 인물 번호 순서로 고릅니다(1 번째→<Subject 1>). 외모 설명이 있는 RefMod 는 설명도 들어갑니다. 장소와 시간이 붙은 움직임・대사를 쓰면 각 인물의 위치(화면 왼쪽・가운데・오른쪽)를 더해 6 절 프롬프트를 만듭니다. 움직임 칸에 subject_definitions: 로 시작하는 전문을 쓰면 그대로 씁니다. Turbo・Steps 는 CREATE 의 현재 설정입니다.\n「🖼 이미지」로 키프레임 이미지를 불러오면 카메라 보기에 밑그림으로 겹칩니다(「밑그림」으로 농도 전환). 「👤 이미지에서 배치」는 이미지 속 인물을 인식해 인원・서는 위치・방향・자세와 카메라의 위치・높이・부감을 현재 시간에 둡니다(대략적이므로 밑그림을 보며 다듬습니다). 생성의 「이미지를 첫 프레임으로 사용」을 켜면 그 이미지에서 시작합니다.\n「✂ 컷」은 재생 위치에서 샷을 나눕니다(카메라는 컷을 넘어 움직이지 않고, 새 샷은 컷 시점의 카메라에서 시작. 인물 위치는 이어짐). 생성할 때 시간이 붙은 움직임・대사를 컷 시점에서 [Shot N]으로 나누고 각 샷의 구도(전신・무릎 위・가슴 위 등)를 더해 하드 컷으로 잇습니다."},
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
                with gr.Column(elem_classes=["panel"], elem_id="c3d-gen"):
                    _UI["rms"] = gr.Dropdown(choices=_refmod_choices(), value=[], multiselect=True, label="人物の RefMod（人の番号の順）",
                                             elem_id="c3d-rms", container=True)
                    _UI["place"] = gr.Textbox(label="場所・背景", lines=1, elem_id="c3d-place",
                                              placeholder="例: a cozy bookstore cafe in the afternoon, wooden bookshelves along the left wall")
                    _UI["action"] = gr.Textbox(label="動き・セリフ（時刻つき）", lines=4, elem_id="c3d-action",
                                               placeholder="例: 0-2s: <Subject 1> waves and says <d>[Japanese] おはよう</d> 2-5s: <Subject 2> laughs.")
                    _UI["seed"] = gr.Number(value=-1, precision=0, label="Seed（−1 でランダム）", elem_id="c3d-seed")
                    _UI["usekf"] = gr.Checkbox(value=False, label="画像を最初のコマにする", elem_id="c3d-usekf")
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
                    with gr.Row(elem_id="c3d-cutrow"):
                        _UI["cut"] = gr.Button("✂ カット", elem_id="c3d-cut")
                        _UI["uncut"] = gr.Button("カットを消す", elem_id="c3d-uncut")
                with gr.Column(elem_classes=["panel"], elem_id="c3d-status"):
                    _UI["msg"] = gr.Textbox(label="STATUS", lines=4, max_lines=int(g.get("STATUS_MAX_LINES", 200)),
                                            interactive=False, value="")
                with gr.Column(elem_classes=["panel"], elem_id="c3d-res-box"):
                    _UI["gen"] = gr.Button("🎬 生成", elem_id="c3d-run-btn")
                    _UI["result"] = gr.Video(label="RESULT", autoplay=True, height=int(g.get("SEG_BOX_H", 360)) * 2 // 3,
                                             interactive=False, elem_id="c3d-result-video", buttons=g.get("BTN_MEDIA"))
                with gr.Column(elem_classes=["panel"], elem_id="c3d-out-box"):
                    _UI["export"] = gr.Button("🎞 ガイドを書き出す", elem_id="c3d-export")
                    _UI["out"] = gr.Video(label="GUIDE", autoplay=True, loop=True, height=int(g.get("SEG_BOX_H", 360)) * 2 // 3,
                                          interactive=False, elem_id="c3d-out-video", buttons=g.get("BTN_MEDIA"))
                _UI["bridge"] = gr.Textbox(value="", elem_id="c3d-bridge", show_label=False, container=False)
                _UI["res"] = gr.Textbox(value="", elem_id="c3d-res", show_label=False, container=False)
                _UI["kf"] = gr.Textbox(value="", elem_id="c3d-kf", show_label=False, container=False)
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
    u["cut"].click(None, js=_call_js("window.__c3d.addCut();"))
    u["uncut"].click(None, js=_call_js("window.__c3d.removeCut();"))
    u["bridge"].change(_on_bridge, inputs=[u["bridge"]], outputs=[u["dur"], u["aspect"], u["ease"], u["pose"], u["lens"]], queue=False, show_progress="hidden")
    u["export"].click(_after_export, inputs=[u["res"]], outputs=[u["out"], u["msg"]], js=EXPORT_JS, show_progress="minimal")
    u["rms"].focus(lambda v: _ST["ctx"].gr.update(choices=_refmod_choices(), value=v), inputs=[u["rms"]], outputs=[u["rms"]],
                   queue=False, show_progress="hidden")
    u["gen"].click(c3d_generate, inputs=[u["res"], u["rms"], u["place"], u["action"], u["seed"], u["usekf"], u["kf"]],
                   outputs=[u["msg"], u["result"]],
                   js=GEN_JS, concurrency_id="generate", concurrency_limit=1, show_progress="minimal")


def wire(ctx, comps):
    return
