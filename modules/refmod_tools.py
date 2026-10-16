# Copyright (C) 2026 CALMDUST / AiHUB
# SPDX-License-Identifier: Apache-2.0
"""refmod_tools — RefMod の見た目の説明（MiniMax H3 WebUI の拡張モジュール）

WebUI 本体（セル3）がコミット固定で読み込み、`setup` → `build_slot` → `wire` の順に呼ぶ。
本体の関数・状態は `ctx.g`（本体のグローバル）から借りる。単体では動かない。

できること（WebUI ver1.7 #317 で本体に入れたものを、#321 でこちらへ移した）:
  ・RefMod の保存時に、プロンプト補助（Qwen3-VL）へ素材を見せて「変わらない見た目」と服を書かせ、メタに残す
  ・プロンプトの `<Subject k> is @refmod N.`（ラベルの直後が文の終わり）に見た目だけを自動で足す
  ・`<Prompt N>`（`@prompt N`）を見た目＋服の全文に置き換える
  ・FINDER で説明を生成・手直し・保存する
  ・🆕 1.1.0 FINDER の編集パネル（#331）: 種類（concept_type）・タグの書き換え、素材（bundle の members）の
    並べ替え・外す・ほかの RefMod から足す、Stack 動画のコマを消す、直前の 1 回を元に戻す
  ・🆕 1.2.0（#332）: 見た目の説明は FINDER の STATUS の中で直す。編集は 1 つの箱にまとめてタブで切り替え。
    動画のコマを潜在から絵にして STATUS に番号つきで並べる（間引き・見本の差し替えは利用者判断で外した）
  ・🆕 1.3.0（#333）: 編集はすべて STATUS の右のタブ（見た目・服／素材／種類・タグ）。素材・コマは STATUS の上で直接:
    クリックで選ぶ → 🗑 か枠の外へドラッグで消す、画像・動画・音声をドロップ（または ＋）で足す
    （Stack のコマの並びに画像を落とすとコマとして足す。それ以外は新しい素材）
メタ（本家 Luisacaotica/ComfyUI-MiniMaxH3Mod 互換）: `description`＝自然文、`concept_type`＝identity、
分け書きは独自キー `h3webui_desc`＝{"appearance", "outfit"}。bundle は全体に置く。潜在には触らない。
"""
import json
import os
import re

NAME = "refmod_tools"
VERSION = "1.3.0"
API = 1                                   # 本体の MODULE_API と一致しないと読み込まれない
SLOTS = ("refmod_save_opts", "rmb_opts", "refmod_bar2", "rmm_status")

DESC_KEY = "h3webui_desc"
DESC_IMG_MAX = 8                          # 説明を書かせるときに見せる絵の上限
DESC_ON_SAVE_DEFAULT = True               # 保存時に説明を作る（プロンプト補助が有効なときだけ）
AUTO_DESC_DEFAULT = True                  # `<Subject> is @refmod N.` に見た目を自動で足す（利用者判断 2026-10-16: 既定 ON）

# WebUI のセル161（2026-10-16）での実測: 画像 1 枚の RefMod は説明なしで金髪が黒髪に化け、顔の似方 0.27 → 説明ありで 0.51。
# 服はどの構成でもプロンプトどおり。最初の指示では金髪・青い目から欧米人の顔に寄った → 染めた髪は bleached / dyed、
# カラコンは coloured contact lenses と書かせて解消（顔立ちの系統を書き足す案は差が無く不採用＝国籍・民族は書かせない）。
DESC_SYS = (
    "You describe a person for a video generation model. You will see one or more reference images of the same "
    "person. Write only the features that stay the same from image to image. Answer in exactly this form and "
    "nothing else:\n"
    "APPEARANCE: <one line, comma-separated: hair colour, length and style; eye colour and shape; face shape; "
    "eyebrows; skin tone; distinctive marks such as moles, freckles, glasses, piercings>\n"
    "OUTFIT: <one line, comma-separated: the clothing and accessories worn in most of the images>\n"
    "Rules: plain English, concrete visual words, at most 45 words per line. If the hair colour looks dyed or "
    "bleached, write 'dyed' or 'bleached' (e.g. 'bleached platinum blonde hair'); if the eye colour looks like "
    "coloured contact lenses, write 'coloured contact lenses'. Do NOT mention pose, gesture, expression, background, "
    "lighting, camera, image quality, or the person's name. Do NOT guess age, nationality, ethnicity or profession. "
    "Do not write 'the person in the image'; start directly with the features."
)
_BAN = re.compile(
    r"\b(?:\d+\s*-?\s*(?:years?|yrs?)\s*old|aged \d+|teen\w*|twenties|thirties|forties|elderly|middle-aged|"
    r"japanese|asian|korean|chinese|european|caucasian|african|latin[ao]|western|ethnic\w*|nationality)\b", re.I)
_NAME_SKIP = {"stack", "human", "pool", "pooled", "video", "image", "audio", "voice", "refmod"}

# `<Prompt N>` ＝ RefMod N の説明。自動で足すのは `<RefMod N>` の直後が `.`／`。`／行末のときだけ
_PROMPT_TAG_RE = re.compile(r"[<＜]\s*prompt\s*(\d+)\s*[>＞]", re.IGNORECASE)
_REFMOD_BARE_RE = re.compile(r"([<＜]\s*refmod\s*(\d+)\s*[>＞])(?=[ \t]*(?:[.。]|$))", re.IGNORECASE | re.MULTILINE)

_ST = {"ctx": None, "on_save": {"refs": DESC_ON_SAVE_DEFAULT, "builder": DESC_ON_SAVE_DEFAULT},
       "auto": AUTO_DESC_DEFAULT, "ui": {}}

HELP = {
    "refmod": "保存時に**見た目の説明**を作っておくと（要プロンプト補助）、`<Subject 1> is @refmod 1.` のようにラベルで文を終えたとき、"
              "見た目が自動で足されます。服も素材どおりにしたいときは **`@prompt 1`**（見た目＋服）と書きます。説明は FINDER で直せます。",
}

I18N = {
    HELP["refmod"]: {
        "en": "If you write an **appearance description** when saving (needs Prompt Assist), a sentence that ends with the label, "
              "like `<Subject 1> is @refmod 1.`, gets the appearance added automatically. To keep the original outfit too, "
              "write **`@prompt 1`** (appearance + outfit). Descriptions can be edited in FINDER.",
        "zh": "保存时生成**外貌描述**（需要提示词助手）后，像 `<Subject 1> is @refmod 1.` 这样以标签结束句子时，会自动补上外貌。"
              "想连服装也保持原样时，写 **`@prompt 1`**（外貌＋服装）。描述可在 FINDER 中修改。",
        "ko": "저장할 때 **외모 설명**을 만들어 두면(프롬프트 보조 필요) `<Subject 1> is @refmod 1.`처럼 라벨로 문장을 끝냈을 때 "
              "외모가 자동으로 붙습니다. 의상도 소재 그대로 하고 싶으면 **`@prompt 1`**(외모＋의상)이라고 씁니다. 설명은 FINDER에서 고칠 수 있습니다."},
    "RefMod の説明を作れませんでした: {v0}": {"en": "Could not write the RefMod description: {v0}", "zh": "无法生成 RefMod 的描述：{v0}", "ko": "RefMod 설명을 만들지 못했습니다: {v0}"},
    "ℹ️ 見た目の説明は付けませんでした（{v0}）": {"en": "ℹ️ No appearance description was added ({v0})", "zh": "ℹ️ 未添加外貌描述（{v0}）", "ko": "ℹ️ 외모 설명은 붙이지 않았습니다 ({v0})"},
    "⚠️ <Prompt {v0}> に当たる説明がありません（RefMod {v0} が無いか、説明が付いていません）。そのまま残しました": {"en": "⚠️ No description for <Prompt {v0}> (RefMod {v0} is missing or has no description). Left as is", "zh": "⚠️ 没有与 <Prompt {v0}> 对应的描述（RefMod {v0} 不存在或没有描述）。已原样保留", "ko": "⚠️ <Prompt {v0}>에 해당하는 설명이 없습니다 (RefMod {v0}가 없거나 설명이 붙어 있지 않음). 그대로 두었습니다"},
    "⚠️ RefMod の名前の語が入っています（{v0}）。人名なら消してください": {"en": "⚠️ The text contains words from the RefMod name ({v0}). Remove them if they are a person's name", "zh": "⚠️ 文中含有 RefMod 名称中的词（{v0}）。如果是人名请删除", "ko": "⚠️ RefMod 이름의 단어가 들어 있습니다 ({v0}). 사람 이름이면 지워 주세요"},
    "⚠️ 書かない約束の語が入っています（{v0}）。手で直してください": {"en": "⚠️ The text contains words it should not use ({v0}). Please fix it by hand", "zh": "⚠️ 文中含有不应使用的词（{v0}）。请手动修改", "ko": "⚠️ 쓰지 않기로 한 단어가 들어 있습니다 ({v0}). 직접 고쳐 주세요"},
    "⚠️ 見た目の行が書かれませんでした。もう一度押すか、手で書いてください": {"en": "⚠️ No appearance line was written. Press again or write it by hand", "zh": "⚠️ 没有写出外貌一行。请再按一次或手动填写", "ko": "⚠️ 외모 줄이 작성되지 않았습니다. 다시 누르거나 직접 써 주세요"},
    "✍️ 書きました。直してから「説明を保存」を押してください": {"en": "✍️ Done. Edit it if needed, then press \"Save description\"", "zh": "✍️ 已写好。修改后请按“保存描述”", "ko": "✍️ 작성했습니다. 고친 뒤 \"설명 저장\"을 눌러 주세요"},
    "❌ RefMod を 1 件選んでください": {"en": "❌ Select one RefMod", "zh": "❌ 请选择 1 个 RefMod", "ko": "❌ RefMod를 1개 선택해 주세요"},
    "❌ 説明を保存できませんでした: {v0}": {"en": "❌ Could not save the description: {v0}", "zh": "❌ 无法保存描述：{v0}", "ko": "❌ 설명을 저장하지 못했습니다: {v0}"},
    "プロンプト補助が有効ではありません（セル2 の TE_LLM_ENABLE を ON にして読み直してください）": {"en": "Prompt Assist is not enabled (turn on TE_LLM_ENABLE in Cell 2 and reload)", "zh": "提示词助手未启用（请在单元格 2 中开启 TE_LLM_ENABLE 并重新加载）", "ko": "프롬프트 보조가 활성화되어 있지 않습니다 (셀 2의 TE_LLM_ENABLE을 켜고 다시 불러오세요)"},
    "説明に使える絵がありません（画像・動画の素材か、WebUI で保存した RefMod の見本が要ります）": {"en": "No pictures to describe (needs image/video sources, or a RefMod saved in the WebUI with previews)", "zh": "没有可用于描述的图片（需要图片/视频素材，或在 WebUI 中保存的带预览的 RefMod）", "ko": "설명에 쓸 그림이 없습니다 (이미지·영상 소재나 WebUI에서 저장한 RefMod의 견본이 필요합니다)"},
    "💾 説明を保存しました: {v0}": {"en": "💾 Description saved: {v0}", "zh": "💾 已保存描述：{v0}", "ko": "💾 설명을 저장했습니다: {v0}"},
    "ℹ️ <RefMod {v0}>（{v1}）には見た目の説明が無いので足しませんでした（FINDER で付けられます）": {"en": "ℹ️ <RefMod {v0}> ({v1}) has no appearance description, so nothing was added (you can add one in FINDER)", "zh": "ℹ️ <RefMod {v0}>（{v1}）没有外貌描述，因此未添加（可在 FINDER 中添加）", "ko": "ℹ️ <RefMod {v0}>({v1})에는 외모 설명이 없어 붙이지 않았습니다 (FINDER에서 붙일 수 있습니다)"},
    "ℹ️ 見た目の説明の自動挿入: {v0} ／ 選択中の RefMod {v1} ／ 文末のラベル {v2}": {"en": "ℹ️ Auto appearance description: {v0} / selected RefMods {v1} / labels ending a sentence {v2}", "zh": "ℹ️ 自动添加外貌描述：{v0} ／ 已选 RefMod {v1} ／ 句末标签 {v2}", "ko": "ℹ️ 외모 설명 자동 삽입: {v0} / 선택한 RefMod {v1} / 문장 끝 라벨 {v2}"},
    "📝 <RefMod {v0}> に見た目の説明を足しました": {"en": "📝 Added the appearance description to <RefMod {v0}>", "zh": "📝 已为 <RefMod {v0}> 添加外貌描述", "ko": "📝 <RefMod {v0}>에 외모 설명을 붙였습니다"},
    "📝 見た目の説明を付けました（FINDER で直せます）: {v0}": {"en": "📝 Appearance description added (editable in FINDER): {v0}", "zh": "📝 已添加外貌描述（可在 FINDER 中修改）：{v0}", "ko": "📝 외모 설명을 붙였습니다 (FINDER에서 고칠 수 있습니다): {v0}"},
    "🗑 説明を消しました: {v0}": {"en": "🗑 Description removed: {v0}", "zh": "🗑 已删除描述：{v0}", "ko": "🗑 설명을 지웠습니다: {v0}"},
    "⏳ もう書いています": {"en": "⏳ Already writing", "zh": "⏳ 正在撰写中", "ko": "⏳ 이미 쓰는 중입니다"},
    "⏳ 生成中は使えません。終わってからもう一度押してください": {"en": "⏳ Not available while generating. Press again when it finishes", "zh": "⏳ 生成过程中无法使用。完成后请再按一次", "ko": "⏳ 생성 중에는 쓸 수 없습니다. 끝난 뒤 다시 눌러 주세요"},
    "❌ 書けませんでした: {v0}": {"en": "❌ Could not write it: {v0}", "zh": "❌ 无法撰写：{v0}", "ko": "❌ 쓰지 못했습니다: {v0}"},
    "服（@prompt で使う。自動では足さない）": {"en": "Outfit (used by @prompt; not added automatically)", "zh": "服装（用于 @prompt，不会自动添加）", "ko": "의상 (@prompt에서 사용. 자동으로는 붙이지 않음)"},
    "見た目の説明も作る": {"en": "Also write an appearance description", "zh": "同时生成外貌描述", "ko": "외모 설명도 만들기"},
    "見た目の説明を自動で足す": {"en": "Add the appearance description automatically", "zh": "自动添加外貌描述", "ko": "외모 설명을 자동으로 붙이기"},
    "見た目（髪・目・顔・目印）": {"en": "Appearance (hair, eyes, face, marks)", "zh": "外貌（头发、眼睛、脸、特征）", "ko": "외모 (머리·눈·얼굴·특징)"},
    "✍️ 説明を生成": {"en": "✍️ Generate description", "zh": "✍️ 生成描述", "ko": "✍️ 설명 생성"},
    "💾 説明を保存": {"en": "💾 Save description", "zh": "💾 保存描述", "ko": "💾 설명 저장"},
    # 🆕 1.1.0 編集パネル（#331）
    # 🆕 1.3.0（#333）
    "＋ 素材 {v0} にコマを {v1} 枚足しました（{v2} → {v3}）": {"en": "＋ Added {v1} frame(s) to source {v0} ({v2} → {v3})", "zh": "＋ 已为素材 {v0} 添加 {v1} 帧（{v2} → {v3}）", "ko": "＋ 소재 {v0}에 프레임 {v1}장을 더했습니다 ({v2} → {v3})"},
    "＋ 素材を {v0} 件足しました": {"en": "＋ Added {v0} source(s)", "zh": "＋ 已添加 {v0} 个素材", "ko": "＋ 소재 {v0}개를 더했습니다"},
    "クリックで選択 → 🗑 か枠の外へドラッグで削除／ファイルをドロップで追加": {"en": "Click to select → 🗑 or drag out to remove / drop files to add", "zh": "点击选择 → 🗑 或拖到框外删除／拖入文件添加", "ko": "클릭으로 선택 → 🗑 또는 밖으로 끌어 삭제 / 파일을 끌어다 놓아 추가"},
    "画像": {"en": "Image", "zh": "图片", "ko": "이미지"},
    "動画": {"en": "Video", "zh": "视频", "ko": "동영상"},
    "音声": {"en": "Audio", "zh": "音频", "ko": "음성"},
    "❌ コマを足せるのは正方形の Stack の素材だけです（画像は新しい素材として足してください）": {"en": "❌ Frames can only be added to square Stack sources (add the image as a new source instead)", "zh": "❌ 只能向正方形的 Stack 素材添加帧（请把图片作为新素材添加）", "ko": "❌ 프레임은 정사각형 Stack 소재에만 더할 수 있습니다 (이미지는 새 소재로 더해 주세요)"},
    "❌ pool 型の素材にはコマを足せません": {"en": "❌ Frames cannot be added to a pool-type source", "zh": "❌ 无法向 pool 型素材添加帧", "ko": "❌ pool 형 소재에는 프레임을 더할 수 없습니다"},
    "❌ 足すコマの大きさが合いませんでした": {"en": "❌ The new frame's size did not match", "zh": "❌ 新帧的尺寸不一致", "ko": "❌ 더할 프레임의 크기가 맞지 않았습니다"},
    "❌ 足す素材をエンコードできませんでした": {"en": "❌ Could not encode the sources to add", "zh": "❌ 无法编码要添加的素材", "ko": "❌ 더할 소재를 인코딩하지 못했습니다"},
    "選んだものを消す": {"en": "Remove selected", "zh": "删除所选", "ko": "선택한 것 지우기"},
    "ファイルを選んで足す": {"en": "Choose files to add", "zh": "选择文件添加", "ko": "파일을 골라 더하기"},
    "素材（{v0}）": {"en": "Sources ({v0})", "zh": "素材（{v0}）", "ko": "소재 ({v0})"},
    "見た目・服": {"en": "Appearance & outfit", "zh": "外貌与服装", "ko": "외모·의상"},
    "素材やコマは左の STATUS の上で直せます（クリックで選ぶ → 🗑 か枠の外へドラッグで消す／画像・動画・音声をドロップするか ＋ で足す。Stack のコマの並びに画像を落とすとコマになります）。中身（潜在）を書き換えるので、直前の 1 回だけ元に戻せます。": {"en": "Sources and frames can be edited directly in STATUS on the left (click to select → 🗑 or drag out to remove / drop images, videos or audio, or use ＋, to add; images dropped on a Stack's frame row become frames). This rewrites the contents (latents), so only the last edit can be undone.", "zh": "素材和帧可在左侧 STATUS 中直接修改（点击选择 → 🗑 或拖到框外删除／拖入图片、视频、音频或用 ＋ 添加；把图片拖到 Stack 的帧列上会成为帧）。这会改写内容（潜变量），只能撤销上一次编辑。", "ko": "소재와 프레임은 왼쪽 STATUS에서 바로 고칠 수 있습니다 (클릭으로 선택 → 🗑 또는 밖으로 끌어 삭제 / 이미지·동영상·음성을 끌어다 놓거나 ＋로 추가. Stack 프레임 줄에 이미지를 놓으면 프레임이 됩니다). 내용(잠재)을 다시 쓰므로 직전 1회만 되돌릴 수 있습니다."},
    # 🆕 1.2.0（#332）
    "素材 {v0} のコマ（{v1}）": {"en": "Source {v0} frames ({v1})", "zh": "素材 {v0} 的帧（{v1}）", "ko": "소재 {v0}의 프레임 ({v1})"},
    "コマの絵を作れませんでした: {v0}": {"en": "Could not make the frame pictures: {v0}", "zh": "无法生成帧图像：{v0}", "ko": "프레임 그림을 만들지 못했습니다: {v0}"},
    "💾 種類・タグを保存しました: {v0}": {"en": "💾 Type and tags saved: {v0}", "zh": "💾 已保存类型和标签：{v0}", "ko": "💾 종류·태그를 저장했습니다: {v0}"},
    "✂ 素材 {v0} のコマ: {v1} → {v2}": {"en": "✂ Source {v0} frames: {v1} → {v2}", "zh": "✂ 素材 {v0} 的帧：{v1} → {v2}", "ko": "✂ 소재 {v0}의 프레임: {v1} → {v2}"},
    "↕ 素材 {v0} を {v1} 番目へ動かしました": {"en": "↕ Moved source {v0} to position {v1}", "zh": "↕ 已将素材 {v0} 移到第 {v1} 位", "ko": "↕ 소재 {v0}을(를) {v1}번째로 옮겼습니다"},
    "✕ 素材 {v0} を外しました": {"en": "✕ Removed source {v0}", "zh": "✕ 已移除素材 {v0}", "ko": "✕ 소재 {v0}을(를) 뺐습니다"},
    "＋ {v0} の素材 {v1} 件を足しました": {"en": "＋ Added {v1} source(s) from {v0}", "zh": "＋ 已添加 {v0} 的 {v1} 个素材", "ko": "＋ {v0}의 소재 {v1}개를 더했습니다"},
    "↩ 直前の編集を元に戻しました: {v0}": {"en": "↩ Undid the last edit: {v0}", "zh": "↩ 已撤销上一次编辑：{v0}", "ko": "↩ 직전 편집을 되돌렸습니다: {v0}"},
    "元に戻せる編集がありません": {"en": "There is no edit to undo", "zh": "没有可撤销的编辑", "ko": "되돌릴 편집이 없습니다"},
    "❌ 素材を選んでください": {"en": "❌ Select a source", "zh": "❌ 请选择素材", "ko": "❌ 소재를 선택해 주세요"},
    "❌ 最後の 1 件は外せません（RefMod ごと消すときは「🗑 選択中の RefMod を削除」）": {"en": "❌ The last source cannot be removed (to delete the whole RefMod, use \"🗑 Delete selected RefMod\")", "zh": "❌ 无法移除最后 1 个素材（要删除整个 RefMod，请用“🗑 删除所选 RefMod”）", "ko": "❌ 마지막 1개는 뺄 수 없습니다 (RefMod째 지우려면 \"🗑 선택한 RefMod 삭제\")"},
    "❌ 足す RefMod を選んでください": {"en": "❌ Select a RefMod to add", "zh": "❌ 请选择要添加的 RefMod", "ko": "❌ 더할 RefMod를 선택해 주세요"},
    "❌ 素材が 256 件を超えます": {"en": "❌ That would exceed 256 sources", "zh": "❌ 素材将超过 256 个", "ko": "❌ 소재가 256개를 넘습니다"},
    "❌ コマを減らせるのは動画（Stack）の素材だけです": {"en": "❌ Only video (Stack) sources can have frames removed", "zh": "❌ 只有视频（Stack）素材可以减少帧", "ko": "❌ 프레임을 줄일 수 있는 것은 동영상(Stack) 소재뿐입니다"},
    "❌ 1 コマは残してください": {"en": "❌ Keep at least one frame", "zh": "❌ 请至少保留 1 帧", "ko": "❌ 1프레임은 남겨 주세요"},
    "❌ 消すコマを選んでください": {"en": "❌ Select the frames to remove", "zh": "❌ 请选择要删除的帧", "ko": "❌ 지울 프레임을 선택해 주세요"},
    "変更はありません": {"en": "No changes", "zh": "没有更改", "ko": "변경 사항이 없습니다"},
    "指定なし（generic）": {"en": "Unspecified (generic)", "zh": "未指定（generic）", "ko": "지정 없음 (generic)"},
    "人物・キャラクター（identity）": {"en": "Person / character (identity)", "zh": "人物・角色（identity）", "ko": "인물·캐릭터 (identity)"},
    "ポーズ・動き（pose_motion）": {"en": "Pose / motion (pose_motion)", "zh": "姿势・动作（pose_motion）", "ko": "포즈·동작 (pose_motion)"},
    "服（clothing）": {"en": "Clothing (clothing)", "zh": "服装（clothing）", "ko": "의상 (clothing)"},
    "背景・場所（background）": {"en": "Background / location (background)", "zh": "背景・场所（background）", "ko": "배경·장소 (background)"},
    "画風・色調（style）": {"en": "Style / grade (style)", "zh": "画风・色调（style）", "ko": "화풍·색조 (style)"},
    "声（voice）": {"en": "Voice (voice)", "zh": "声音（voice）", "ko": "목소리 (voice)"},
    "歌声（singing）": {"en": "Singing (singing)", "zh": "歌声（singing）", "ko": "노랫소리 (singing)"},
    "曲調（music_style）": {"en": "Music style (music_style)", "zh": "曲风（music_style）", "ko": "곡조 (music_style)"},
    "効果音（sound_fx）": {"en": "Sound effects (sound_fx)", "zh": "音效（sound_fx）", "ko": "효과음 (sound_fx)"},
    "環境音（ambience）": {"en": "Ambience (ambience)", "zh": "环境音（ambience）", "ko": "환경음 (ambience)"},
    "種類": {"en": "Type", "zh": "类型", "ko": "종류"},
    "タグ": {"en": "Tags", "zh": "标签", "ko": "태그"},
    "説明": {"en": "Description", "zh": "描述", "ko": "설명"},
    "❌ 編集できませんでした: {v0}": {"en": "❌ Could not edit: {v0}", "zh": "❌ 无法编辑：{v0}", "ko": "❌ 편집하지 못했습니다: {v0}"},
    "種類・タグ": {"en": "Type and tags", "zh": "类型与标签", "ko": "종류·태그"},
    "種類（concept_type）": {"en": "Type (concept_type)", "zh": "类型（concept_type）", "ko": "종류 (concept_type)"},
    "タグ（カンマ区切り）": {"en": "Tags (comma-separated)", "zh": "标签（逗号分隔）", "ko": "태그 (쉼표로 구분)"},
    "💾 種類・タグを保存": {"en": "💾 Save type and tags", "zh": "💾 保存类型和标签", "ko": "💾 종류·태그 저장"},
    "素材": {"en": "Source", "zh": "素材", "ko": "소재"},
    "ほかの RefMod の素材を足す": {"en": "Add sources from another RefMod", "zh": "添加其他 RefMod 的素材", "ko": "다른 RefMod의 소재 더하기"},
    "＋ 足す": {"en": "＋ Add", "zh": "＋ 添加", "ko": "＋ 더하기"},
    "↩ 直前の編集を元に戻す": {"en": "↩ Undo the last edit", "zh": "↩ 撤销上一次编辑", "ko": "↩ 직전 편집 되돌리기"},
}

# 字・ボタンは本体の CSS 変数（--h3-*）に合わせる。チェックの字は同じ箱の見出し・本体の RefMod 保存のチェックと同じ 12px・muted（#325）、
# FINDER のボタンは「CREATE で使う」「変更する」と同じ見た目
CSS = """
/* ---- 拡張モジュール refmod_tools ---- */
#refmod-desc-cb label span, #refmod-desc-cb span, #rmb-desc label span, #rmb-desc span,
#refmod-auto-desc label span, #refmod-auto-desc span {
    font-size: 12px !important; color: var(--h3-muted) !important;
    letter-spacing: 0.04em !important; font-weight: 400 !important; line-height: 1.5 !important;
}
#refmod-desc-cb input[type="checkbox"], #rmb-desc input[type="checkbox"], #refmod-auto-desc input[type="checkbox"] {
    accent-color: var(--h3-accent) !important; flex: 0 0 auto !important;
}
#refmod-desc-cb { align-self: center !important; padding: 0 !important; min-width: 0 !important; }
#rmm-desc-gen-btn, #rmm-desc-save-btn {
    width: 100% !important; height: 34px !important; margin-top: 8px !important;
    background: var(--h3-elev) !important; border: 1px solid var(--h3-border2) !important;
    border-radius: 6px !important; color: var(--h3-muted) !important;
    font-size: 11px !important; letter-spacing: 0.12em !important; font-weight: 400 !important;
}
#rmm-desc-gen-btn:hover, #rmm-desc-save-btn:hover {
    background: var(--h3-border) !important; border-color: var(--h3-border-hover) !important; color: var(--h3-text) !important;
}
/* 🆕 1.1.0 編集パネル: ボタンは「変更する」（#rmm-apply-btn）、選択欄の字は「フォルダ」欄（#rmm-folder-dd）と同じ */
.rmm-ed-btn {
    width: 100% !important; height: 34px !important; margin-top: 8px !important;
    background: var(--h3-elev) !important; border: 1px solid var(--h3-border2) !important;
    border-radius: 6px !important; color: var(--h3-muted) !important;
    font-size: 11px !important; letter-spacing: 0.12em !important; font-weight: 400 !important;
}
.rmm-ed-btn:hover:not(:disabled) {
    background: var(--h3-border) !important; border-color: var(--h3-border-hover) !important; color: var(--h3-text) !important;
}
.rmm-ed-btn:disabled { opacity: 0.45 !important; cursor: default !important; }
#rmm-ed-row { gap: 6px !important; flex-wrap: nowrap !important; }
#rmm-ed-row .rmm-ed-btn { min-width: 0 !important; padding: 0 4px !important; letter-spacing: 0.04em !important; }
.rmm-ed-dd .container, .rmm-ed-dd > .container, .rmm-ed-dd .container > span {
    font-size: 12px !important; color: var(--h3-muted) !important;
    letter-spacing: 0.04em !important; font-weight: 400 !important;
}
.rmm-ed-dd .container input, .rmm-ed-dd .container .wrap-inner {
    color: var(--h3-muted) !important; font-size: 12px !important; letter-spacing: 0.04em !important;
}
#rmm-ed-frames { gap: 0 !important; padding: 0 !important; background: none !important; border: 0 !important; }
/* コマの欄の見出し・数字・間引きの見出しも「素材」「名前」と同じ 12px・muted・0.04em（.wrap の規則で muted2 になるのを上書き）*/
#rmm-ed-frdrop span, #rmm-ed-frdrop label span {
    font-size: 12px !important; color: var(--h3-muted) !important;
    letter-spacing: 0.04em !important; font-weight: 400 !important;
}
#rmm-ed-hint p { font-size: 12px !important; color: var(--h3-faint) !important; margin: 8px 0 0 0 !important; }
/* 🆕 1.2.0 STATUS の右（見た目の説明）。ボタン 2 つは横並び */
#rmm-desc-row { gap: 6px !important; flex-wrap: nowrap !important; }
#rmm-desc-row .rmm-ed-btn { min-width: 0 !important; letter-spacing: 0.06em !important; }
#rmm-status-side .form { background: none !important; border: 0 !important; box-shadow: none !important; padding: 0 !important; }
#rmm-status-side label span, #rmm-status-side [data-testid="block-info"] {
    font-size: 12px !important; color: var(--h3-muted) !important; letter-spacing: 0.04em !important; font-weight: 400 !important;
}
#rmm-status-side textarea { font-size: 12px !important; line-height: 1.55 !important; }
/* 編集の箱のタブ（アコーディオンの見出しと同じ 12px・muted、選んでいるタブはアクセント色の下線）*/
#rmm-ed-tabs { margin-top: 2px !important; }
#rmm-ed-tabs .tab-wrapper, #rmm-ed-tabs [role="tablist"] { border-bottom: 1px solid var(--h3-border) !important; }
#rmm-ed-tabs button[role="tab"] {
    font-size: 12px !important; color: var(--h3-muted) !important; letter-spacing: 0.08em !important;
    font-weight: 400 !important; padding: 6px 10px !important;
}
#rmm-ed-tabs button[role="tab"][aria-selected="true"] { color: var(--h3-accent) !important; }
#rmm-ed-tabs .tabitem { padding: 6px 0 0 0 !important; border: 0 !important; background: none !important; }
/* 🆕 1.3.0 STATUS の上の素材・コマ（本体の素材の並びはこちらに置き換える）*/
#rmm-detail .rmm-d-refs { display: none !important; }
#rmm-detail .rmm-d-sec { margin: 10px -9px 0 -9px; padding: 8px; border: 1px dashed transparent; border-radius: 8px;
                         transition: border-color .12s, background .12s; }
#rmm-detail .rmm-d-sec.over { border-color: var(--h3-accent); background: var(--h3-elev); }
#rmm-detail .rmm-d-shead { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; min-height: 24px; }
#rmm-detail .rmm-d-stitle { font-size: 11px; color: var(--h3-faint); letter-spacing: 0.06em; white-space: nowrap; flex: 0 0 auto; }
#rmm-detail .rmm-d-hint { font-size: 10px; color: var(--h3-faint); letter-spacing: 0.04em; opacity: .8; flex: 1 1 auto;
                          min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
#rmm-detail .rmm-d-trash { margin-left: auto; height: 24px; min-width: 32px; padding: 0 8px; border-radius: 6px;
                           border: 1px solid var(--h3-border2); background: var(--h3-elev); color: var(--h3-muted);
                           font-size: 12px; line-height: 22px; cursor: pointer; }
#rmm-detail .rmm-d-trash:hover:not(:disabled) { background: var(--h3-border); color: var(--h3-text); }
#rmm-detail .rmm-d-trash:disabled { opacity: .35; cursor: default; }
#rmm-detail .rmm-d-strip { display: flex; flex-wrap: wrap; gap: 6px; }
#rmm-detail .rmm-it { position: relative; width: 56px; height: 56px; border-radius: 6px; overflow: hidden; cursor: pointer;
                      border: 1px solid var(--h3-border); background: var(--h3-bg); user-select: none; touch-action: none; }
#rmm-detail .rmm-it.rmm-mem { width: 72px; height: 72px; }
#rmm-detail .rmm-it img { width: 100%; height: 100%; object-fit: cover; display: block; pointer-events: none; }
#rmm-detail .rmm-it-icon { display: flex; width: 100%; height: 100%; align-items: center; justify-content: center; font-size: 22px; }
#rmm-detail .rmm-f-none { display: block; width: 100%; height: 100%; }
#rmm-detail .rmm-it-no { position: absolute; left: 3px; top: 2px; font-size: 10px; line-height: 1.2; padding: 0 4px;
                         border-radius: 3px; color: #fff; background: rgba(0, 0, 0, 0.55); font-variant-numeric: tabular-nums; }
#rmm-detail .rmm-it-cap { position: absolute; left: 0; right: 0; bottom: 0; font-size: 9px; line-height: 1.5; padding: 0 3px;
                          color: #fff; background: rgba(0, 0, 0, 0.5); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
#rmm-detail .rmm-it.sel { outline: 2px solid var(--h3-accent); outline-offset: -2px; border-color: var(--h3-accent); }
#rmm-detail .rmm-it.dragging { opacity: .45; }
#rmm-detail .rmm-it.out, #rmm-detail .rmm-it.gone { opacity: .15; }
#rmm-detail .rmm-add { display: flex; align-items: center; justify-content: center; font-size: 20px; color: var(--h3-faint);
                       border-style: dashed; background: none; }
#rmm-detail .rmm-add:hover { color: var(--h3-accent); border-color: var(--h3-accent); }
.rmm-ghost { position: fixed !important; z-index: 9999; width: 56px; height: 56px; border-radius: 6px; overflow: hidden;
             pointer-events: none; box-shadow: 0 4px 14px rgba(0, 0, 0, .3); border: 1px solid var(--h3-border); }
.rmm-ghost img { width: 100%; height: 100%; object-fit: cover; display: block; }
.rmm-ghost .rmm-it-cap { display: none; }
.rmm-ghost.out { opacity: .4; outline: 2px solid #d9534f; }
#rmm-fr-act, #rmm-fr-target, #rmm-fr-file { display: none !important; }
/* 見た目と服の箱の間は、ほかの欄どうしと同じくらい空ける */
#rmm-desc-of { margin-top: 12px !important; }
#rmm-desc-row { margin-top: 4px !important; }
"""


# ---------------------------------------------------------------- 本体から借りるもの
def _g(name):
    return _ST["ctx"].g[name]


def _T(s, **kw):
    return _ST["ctx"].T(s, **kw)


def _log(msg):
    try:
        _ST["ctx"].log(msg)
    except Exception:                                             # noqa: BLE001
        pass


# ---------------------------------------------------------------- 説明の読み書き
def desc_get(name):
    """{"appearance", "outfit"}（無ければ空の値）。本家製で identity の description だけあるものは見た目として扱う"""
    try:
        meta = _g("refmod_load")(name)[1] or {}
    except Exception:                                             # noqa: BLE001
        return {"appearance": "", "outfit": ""}
    d = meta.get(DESC_KEY)
    if isinstance(d, dict):
        return {"appearance": str(d.get("appearance") or "").strip(), "outfit": str(d.get("outfit") or "").strip()}
    if str(meta.get("concept_type") or "") == "identity" and str(meta.get("description") or "").strip():
        return {"appearance": str(meta["description"]).strip().rstrip("."), "outfit": ""}
    return {"appearance": "", "outfit": ""}


def desc_full(d):
    """`@prompt N` に入れる全文（見た目＋服）"""
    ap, of = str(d.get("appearance") or "").strip().rstrip("."), str(d.get("outfit") or "").strip().rstrip(".")
    return f"{ap}, wearing {of}" if (ap and of) else (ap or (f"wearing {of}" if of else ""))


def _meta_rewrite(name, mutate):
    """RefMod のヘッダ（メタ）だけ書き換える。潜在はそのまま書き戻す（safetensors はヘッダだけの更新ができないため）"""
    from safetensors import safe_open
    from safetensors.torch import save_file
    path = os.path.join(_g("REFMOD_DIR"), name + ".safetensors")
    with safe_open(path, "pt") as f:
        hdr = dict(f.metadata() or {})
        tens = {k: f.get_tensor(k) for k in f.keys()}
    key = "refmod_meta" if "refmod_meta" in hdr or "audio_refmod_meta" not in hdr else "audio_refmod_meta"
    meta = json.loads(hdr.get(key) or "{}")
    mutate(meta)
    hdr[key] = json.dumps(meta)
    tmp = path + ".part"
    save_file(tens, tmp, metadata=hdr)
    os.replace(tmp, path)
    _g("_REFMOD")["cache"].pop(name, None)


def desc_set(name, appearance, outfit):
    """説明を RefMod に書く（空なら消す）。concept_type は説明があれば identity（映像を含むときだけ）"""
    ap, of = str(appearance or "").strip().rstrip("."), str(outfit or "").strip().rstrip(".")
    try:
        items = _g("refmod_load")(name)[0]
    except Exception:                                             # noqa: BLE001
        items = []
    has_vis = any(k != "audio" for k, _z in items)

    def _mut(meta):
        if ap or of:
            meta[DESC_KEY] = {"appearance": ap, "outfit": of}
            meta["description"] = (ap + ("." if ap else "") + (f" Usually wears {of}." if of else "")).strip()
            if has_vis:
                meta["concept_type"] = "identity"
        else:
            meta.pop(DESC_KEY, None)
            meta["description"] = ""
            if meta.get("concept_type") == "identity":
                meta["concept_type"] = "generic"
        for m in meta.get("members") or []:                       # bundle: 説明は全体に置き、各要素は種類だけ合わせる
            if isinstance(m, dict) and m.get("kind") != "audio" and has_vis and (ap or of):
                m["concept_type"] = "identity"
    _meta_rewrite(name, _mut)


# ---------------------------------------------------------------- 説明を書かせる
def _frames(paths):
    """説明用の絵（画像はそのまま、動画は先頭のサムネイル）。DESC_IMG_MAX 枚まで"""
    out = []
    for p in paths or []:
        if len(out) >= DESC_IMG_MAX:
            break
        try:
            src = p if _g("is_still")(p) else (_g("make_thumb")(p) or "")
            if src and os.path.isfile(src):
                out.append(src)
        except Exception:                                         # noqa: BLE001
            continue
    return out


def desc_sources(name):
    """保存済み RefMod の見本（素材ごと 1 枚。WebUI で保存したものだけ持つ）"""
    try:
        items = _g("refmod_load")(name)[0]
    except Exception:                                             # noqa: BLE001
        return []
    prev = _g("_refmod_prev_path")
    return [p for i, (k, _z) in enumerate(items) if k != "audio"
            for p in [prev(name, i)] if os.path.isfile(p)][:DESC_IMG_MAX]


def describe(paths, name=""):
    """プロンプト補助に絵を見せて (見た目, 服, 注意の行リスト) を書かせる。使えなければ例外"""
    from PIL import Image
    if not _g("llm_available")():
        raise RuntimeError(_T('プロンプト補助が有効ではありません（セル2 の TE_LLM_ENABLE を ON にして読み直してください）'))
    busy = _g("_LLM_BUSY")
    if busy.is_set():
        raise RuntimeError(_T('⏳ もう書いています'))
    imgs = _frames(paths)
    if not imgs:
        raise RuntimeError(_T('説明に使える絵がありません（画像・動画の素材か、WebUI で保存した RefMod の見本が要ります）'))
    side = int(_ST["ctx"].g.get("LLM_IMG_SIDE", 1024))
    content = []
    for i, p in enumerate(imgs):
        with Image.open(p) as im:
            im = im.convert("RGB")
            im.thumbnail((side, side), Image.LANCZOS)
            content += [{"type": "text", "text": f"Reference image {i + 1}:"}, {"type": "image", "image": im.copy()}]
    content.append({"type": "text", "text": "Describe this person now, in the required form."})
    msgs = [{"role": "system", "content": [{"type": "text", "text": DESC_SYS}]},
            {"role": "user", "content": content}]
    busy.set()
    acc = ""
    try:
        for piece in _g("te_llm_stream")(msgs, max_new_tokens=220):
            if not isinstance(piece, dict):
                acc += piece
    finally:
        busy.clear()
    txt = _g("_llm_clean")(acc)

    def _line(key):
        m = re.search(rf"{key}\s*:\s*(.+)", txt, re.I)
        return m.group(1).strip().rstrip(".") if m else ""
    ap, of = _line("APPEARANCE"), _line("OUTFIT")
    notes = []
    if not ap:
        notes.append(_T('⚠️ 見た目の行が書かれませんでした。もう一度押すか、手で書いてください'))
    bad = sorted(set(m.group(0).lower() for m in _BAN.finditer(ap + " " + of)))
    if bad:
        notes.append(_T('⚠️ 書かない約束の語が入っています（{v0}）。手で直してください', v0=", ".join(bad)))
    leaf = str(name or "").split("/")[-1]
    words = [w for w in re.split(r"[^A-Za-z]+", leaf) if len(w) >= 3 and w.lower() not in _NAME_SKIP]
    hit = [w for w in words if re.search(rf"\b{re.escape(w)}\b", ap + " " + of, re.I)]
    if hit:
        notes.append(_T('⚠️ RefMod の名前の語が入っています（{v0}）。人名なら消してください', v0=", ".join(hit)))
    return ap, of, notes


# ---------------------------------------------------------------- 🆕 1.1.0 編集パネル（#331）
# 本家（Luisacaotica/ComfyUI-MiniMaxH3Mod）の種類。値は本家と同じ英語、画面は日本語（翻訳表）
CONCEPT_TYPES = ("generic", "identity", "pose_motion", "clothing", "background", "style",
                 "voice", "singing", "music_style", "sound_fx", "ambience")
_AUDIO_TYPES = {"voice", "singing", "music_style", "sound_fx", "ambience"}
EDIT_BACKUP_DIR = "_backup"               # REFMOD_DIR の下（`_` で始まるので一覧には出ない）。RefMod ごとに直前の 1 回
_TOP_KEEP = (DESC_KEY, "description", "concept_type", "tags")   # bundle の全体に置く独自・共通のキー


def _ctype_label(v):
    return {"generic": _T("指定なし（generic）"), "identity": _T("人物・キャラクター（identity）"),
            "pose_motion": _T("ポーズ・動き（pose_motion）"), "clothing": _T("服（clothing）"),
            "background": _T("背景・場所（background）"), "style": _T("画風・色調（style）"),
            "voice": _T("声（voice）"), "singing": _T("歌声（singing）"), "music_style": _T("曲調（music_style）"),
            "sound_fx": _T("効果音（sound_fx）"), "ambience": _T("環境音（ambience）")}.get(v, v)


def _path(name):
    return os.path.join(_g("REFMOD_DIR"), name + ".safetensors")


def _read_raw(name):
    """→ (ヘッダ dict, メタのキー, メタ, [(メンバーのメタ, 潜在)])。standalone も 1 件の並びにそろえる"""
    from safetensors import safe_open
    with safe_open(_path(name), "pt") as f:
        hdr = dict(f.metadata() or {})
        key = "audio_refmod_meta" if ("audio_refmod_meta" in hdr and "refmod_meta" not in hdr) else "refmod_meta"
        meta = json.loads(hdr.get(key) or "{}")
        if meta.get("kind") == "bundle":
            mems = [(dict(m), f.get_tensor(f"ref_{i}")) for i, m in enumerate(meta.get("members") or [])]
        else:
            z = f.get_tensor("latent")
            m = dict(meta)
            if not m.get("kind"):
                m["kind"] = "audio" if z.dim() == 4 else ("image" if z.shape[2] == 1 else "video")
            mems = [(m, z)]
    return hdr, key, meta, mems


def _fit_meta(m, z):
    """潜在の形に合わせてメンバーのメタ（kind・latent_t/h/w）を直す。映像は T==1 なら image（本家の検査どおり）"""
    m = dict(m)
    if z.dim() == 4:
        m.update(kind="audio", latent_h=0, latent_w=0, latent_t=int(z.shape[3]))
    else:
        m.update(kind=("image" if int(z.shape[2]) == 1 else "video"), latent_t=int(z.shape[2]),
                 latent_h=int(z.shape[3]), latent_w=int(z.shape[4]))
    return m


def _write_raw(name, hdr, key, top, mems):
    """メンバーの並びを書き戻す。1 件なら standalone（全体のキーを移す）、2 件以上なら bundle v5。
    ヘッダの他のキー・メタの未知のキーは残す（本家の update_member と同じ方針）"""
    from safetensors.torch import save_file
    mems = [(_fit_meta(m, z), z) for m, z in mems]
    names = set()
    for i, (m, _z) in enumerate(mems):                           # 本家は bundle の各要素を名前で確かめるので重複させない
        nm = str(m.get("name") or f"{name.split('/')[-1]}_{i + 1}")
        while nm in names:
            nm += "_b"
        names.add(nm)
        m["name"] = nm
    hdr = {k: v for k, v in hdr.items() if k not in ("refmod_meta", "audio_refmod_meta")}
    if len(mems) == 1:
        m, z = mems[0]
        if top.get("kind") == "bundle":                           # bundle → standalone: 全体の説明・タグを引き継ぐ
            for k in _TOP_KEEP:
                if k in top and (k not in m or not m.get(k)):
                    m[k] = top[k]
            m["name"] = str(top.get("name") or m["name"])
        hdr["audio_refmod_meta" if (key == "audio_refmod_meta" and m["kind"] == "audio") else "refmod_meta"] = json.dumps(m)
        tens = {"latent": z.contiguous()}
    else:
        if top.get("kind") == "bundle":
            meta = dict(top)
        else:                                                     # standalone → bundle: 説明・タグは全体へ
            meta = {"_format_version": 5, "kind": "bundle", "name": str(top.get("name") or name.split("/")[-1])}
            for k in _TOP_KEEP:
                if top.get(k):
                    meta[k] = top[k]
        meta["_format_version"], meta["kind"] = 5, "bundle"
        meta["members"] = [m for m, _z in mems]
        hdr["refmod_meta"] = json.dumps(meta)
        tens = {f"ref_{i}": z.contiguous() for i, (_m, z) in enumerate(mems)}
    path = _path(name)
    tmp = path + ".part"
    save_file(tens, tmp, metadata=hdr)
    os.replace(tmp, path)
    _g("_REFMOD")["cache"].pop(name, None)
    _bk_mark(name)


# ---- 見本の絵（一覧の _<i>.jpg・プロンプト補助の _<i>_p.jpg・🆕 1.2.0 コマの _<i>_f<k>.jpg）は素材の番号で並ぶ
def _td():
    return os.path.join(_g("REFMOD_DIR"), _g("REFMOD_THUMB_DIR"))


def _pic_files(name):
    """{素材の番号: [(後ろの印, パス)]}（ファイル名から。途中に音声＝見本なしが挟まっても取りこぼさない）"""
    pat = re.compile(rf"^{re.escape(name.replace('/', '__'))}_(\d+)((?:_p|_f\d+)?)\.jpg$")
    out = {}
    try:
        for f in os.listdir(_td()):
            m = pat.match(f)
            if m:
                out.setdefault(int(m.group(1)), []).append((m.group(2), os.path.join(_td(), f)))
    except OSError:
        pass
    return out


def _pic_path(name, i, suf=""):
    return os.path.join(_td(), f"{name.replace('/', '__')}_{int(i)}{suf}.jpg")


def _fpath(name, i, k):
    return _pic_path(name, i, f"_f{int(k)}")


def _pics_reorder(name, order, extra=None):
    """新しい並びの i 番目 ← order[i]（元の番号。None なら extra[i]＝(別の RefMod の名前, 番号) から写す）"""
    import shutil
    tmpd = os.path.join(_td(), "_reorder")
    shutil.rmtree(tmpd, ignore_errors=True)
    os.makedirs(tmpd, exist_ok=True)
    old = {}
    for i, fl in _pic_files(name).items():                        # 元をいったん退ける
        for suf, p in fl:
            q = os.path.join(tmpd, f"{i}{suf}.jpg")
            shutil.move(p, q)
            old.setdefault(i, []).append((suf, q))
    for new, o in enumerate(order):
        src = old.get(o, []) if o is not None else (
            _pic_files(extra[new][0]).get(extra[new][1], []) if (extra and new in extra) else [])
        for suf, p in src:
            shutil.copy2(p, _pic_path(name, new, suf))
    shutil.rmtree(tmpd, ignore_errors=True)


# ---- 直前の 1 回を元に戻す（潜在を書き換える操作の前に、本体と見本を控える）
def _bk_dir(name):
    return os.path.join(_g("REFMOD_DIR"), EDIT_BACKUP_DIR, name.replace("/", "__"))


def _backup(name):
    import shutil
    d = _bk_dir(name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    shutil.copy2(_path(name), os.path.join(d, "refmod.safetensors"))
    for i, fl in _pic_files(name).items():
        for suf, p in fl:
            shutil.copy2(p, os.path.join(d, f"{i}{suf}.jpg"))


def _bk_mark(name):
    """控えがあれば、編集後のファイルの更新時刻・大きさを記録する。違っていたら（ほかで書き換えた・改名して同じ名前で
    作り直した等）元に戻すは使わせない＝別物を古い控えで上書きしない"""
    d = _bk_dir(name)
    if os.path.isfile(os.path.join(d, "refmod.safetensors")):
        st = os.stat(_path(name))
        with open(os.path.join(d, "after.json"), "w") as f:
            json.dump({"mtime": st.st_mtime, "size": st.st_size}, f)


def has_backup(name):
    if not name:
        return False
    d = _bk_dir(name)
    try:
        with open(os.path.join(d, "after.json")) as f:
            a = json.load(f)
        st = os.stat(_path(name))
        return (os.path.isfile(os.path.join(d, "refmod.safetensors"))
                and abs(float(a["mtime"]) - st.st_mtime) < 1e-3 and int(a["size"]) == st.st_size)
    except Exception:                                             # noqa: BLE001
        return False


def undo(name):
    import shutil
    d = _bk_dir(name)
    src = os.path.join(d, "refmod.safetensors")
    if not has_backup(name):
        raise RuntimeError(_T('元に戻せる編集がありません'))
    for fl in _pic_files(name).values():
        for _suf, p in fl:
            os.remove(p)
    pat = re.compile(r"^(\d+)((?:_p|_f\d+)?)\.jpg$")
    for f in os.listdir(d):
        m = pat.match(f)
        if m:
            shutil.copy2(os.path.join(d, f), _pic_path(name, m.group(1), m.group(2)))
    shutil.copy2(src, _path(name) + ".part")
    os.replace(_path(name) + ".part", _path(name))
    shutil.rmtree(d, ignore_errors=True)
    _g("_REFMOD")["cache"].pop(name, None)


# ---- 操作（どれも成功したら STATUS に出す 1 行を返す。失敗は例外）
def meta_info(name):
    """編集パネルに出す (種類, タグの文字列, 素材の並び [(kind, z)])"""
    _hdr, _key, top, mems = _read_raw(name)
    ct = str(top.get("concept_type") or "")
    if not ct:                                                    # bundle で全体に無ければ、映像の要素 → 先頭の要素の順
        vis = [m for m, _z in mems if m.get("kind") != "audio"]
        ct = str(((vis or [m for m, _z in mems]) or [{}])[0].get("concept_type") or "generic")
    tags = top.get("tags")
    if not tags and top.get("kind") == "bundle":
        tags = (mems[0][0].get("tags") if mems else []) or []
    return ct, ", ".join(str(t) for t in (tags or [])), [(m.get("kind"), z) for m, z in mems]


def set_meta(name, ctype, tags_txt):
    """種類・タグ（ヘッダだけ。潜在はそのまま）。bundle は全体と各要素の両方へ（本家は要素のメタを見る）"""
    ctype = ctype if ctype in CONCEPT_TYPES else "generic"
    tags = [t.strip() for t in re.split(r"[,、，\n]+", str(tags_txt or "")) if t.strip()]
    hdr, key, top, mems = _read_raw(name)
    if top.get("kind") == "bundle":
        top["concept_type"], top["tags"] = ctype, tags
        for m, _z in mems:
            m["tags"] = list(tags)
            aud = m.get("kind") == "audio"
            if aud == (ctype in _AUDIO_TYPES):                    # 映像の要素に声の種類は付けない（逆も）
                m["concept_type"] = ctype
    else:
        mems[0][0]["concept_type"], mems[0][0]["tags"] = ctype, tags
    _write_raw(name, hdr, key, top, mems)
    return _T('💾 種類・タグを保存しました: {v0}', v0=name)


def _need(name, i=None):
    if not name:
        raise RuntimeError(_T('❌ RefMod を 1 件選んでください'))
    if _g("_BUSY").is_set():
        raise RuntimeError(_T('⏳ 生成中は使えません。終わってからもう一度押してください'))
    hdr, key, top, mems = _read_raw(name)
    if i is not None and not (0 <= int(i) < len(mems)):
        raise RuntimeError(_T('❌ 素材を選んでください'))
    return hdr, key, top, mems


def mem_move(name, i, d):
    hdr, key, top, mems = _need(name, i)
    i, j = int(i), int(i) + int(d)
    if not (0 <= j < len(mems)):
        return None
    _backup(name)
    order = list(range(len(mems)))
    order[i], order[j] = order[j], order[i]
    _write_raw(name, hdr, key, top, [mems[k] for k in order])
    _pics_reorder(name, order)
    return _T('↕ 素材 {v0} を {v1} 番目へ動かしました', v0=f'{i + 1}', v1=f'{j + 1}'), j


def mem_remove(name, i):
    hdr, key, top, mems = _need(name, i)
    if len(mems) <= 1:
        raise RuntimeError(_T('❌ 最後の 1 件は外せません（RefMod ごと消すときは「🗑 選択中の RefMod を削除」）'))
    _backup(name)
    i = int(i)
    order = [k for k in range(len(mems)) if k != i]
    _write_raw(name, hdr, key, top, [mems[k] for k in order])
    _pics_reorder(name, order)
    return _T('✕ 素材 {v0} を外しました', v0=f'{i + 1}'), min(i, len(order) - 1)


def mem_add(name, other):
    hdr, key, top, mems = _need(name)
    if not other or other == name:
        raise RuntimeError(_T('❌ 足す RefMod を選んでください'))
    _h2, _k2, _t2, add = _read_raw(other)
    if len(mems) + len(add) > 256:                                # 本家の bundle の上限
        raise RuntimeError(_T('❌ 素材が 256 件を超えます'))
    _backup(name)
    leaf = other.split("/")[-1]
    add = [(dict(m, name=f"{leaf}_{k + 1}" if len(add) > 1 else leaf), z) for k, (m, z) in enumerate(add)]
    n0 = len(mems)
    _write_raw(name, hdr, key, top, mems + add)
    extra = {n0 + k: (other, k) for k in range(len(add))}
    _pics_reorder(name, list(range(n0)) + [None] * len(add), extra)
    return _T('＋ {v0} の素材 {v1} 件を足しました', v0=other, v1=f'{len(add)}'), n0


def _frames_keep(name, i, keep):
    hdr, key, top, mems = _need(name, i)
    i = int(i)
    m, z = mems[i]
    if z.dim() != 5 or int(z.shape[2]) <= 1:
        raise RuntimeError(_T('❌ コマを減らせるのは動画（Stack）の素材だけです'))
    keep = sorted({int(k) for k in keep if 0 <= int(k) < int(z.shape[2])})
    if not keep:
        raise RuntimeError(_T('❌ 1 コマは残してください'))
    if len(keep) == int(z.shape[2]):
        return None
    _backup(name)
    mems[i] = (m, z[:, :, keep].contiguous())
    _write_raw(name, hdr, key, top, mems)
    # コマの絵も残したコマだけ・番号を詰めて付け直す
    t = int(z.shape[2])
    tmp = {}
    for k in range(t):
        p = _fpath(name, i, k)
        if os.path.isfile(p):
            q = p + ".mv"
            os.replace(p, q)
            tmp[k] = q
    for new_k, old_k in enumerate(keep):
        if old_k in tmp:
            os.replace(tmp.pop(old_k), _fpath(name, i, new_k))
    for q in tmp.values():
        os.remove(q)
    return t, len(keep)


def frames_drop(name, i, drop):
    """選んだコマ（1 始まり）を消す"""
    try:
        t = int(_read_raw(name)[3][int(i)][1].shape[2])
    except Exception:                                             # noqa: BLE001
        t = 0
    gone = {int(x) - 1 for x in (drop or [])}
    r = _frames_keep(name, i, [k for k in range(t) if k not in gone])
    if r is None:
        raise RuntimeError(_T('❌ 消すコマを選んでください'))
    return _T('✂ 素材 {v0} のコマ: {v1} → {v2}', v0=f'{int(i) + 1}', v1=f'{r[0]}', v2=f'{r[1]}')


# ---- 🆕 1.3.0 素材・コマを足す（どちらも本体のエンコード＝生成と同じ手順を借りる。GPU を使う）
_IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
_AUD_EXT = (".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac", ".opus")


def _kind_of(p):
    e = os.path.splitext(str(p))[1].lower()
    return "image" if e in _IMG_EXT else ("audio" if e in _AUD_EXT else "video")


def _enc_ready():
    if _g("_BUSY").is_set():
        raise RuntimeError(_T('⏳ 生成中は使えません。終わってからもう一度押してください'))
    ok, msg = _g("ensure_mode_ui")("Ref2VA")                      # 参照のエンコードは R2V の手順で
    if not ok:
        raise RuntimeError(str(msg))
    return int(_g("calc_frames")(_g("MIN_DURATION")))


def frames_add(name, i, paths):
    """Stack の素材 i の後ろに画像をコマとして足す（保存のときと同じく正方形へ余白でそろえてから 1 枚ずつ VAE）"""
    import math
    import torch
    from PIL import Image
    hdr, key, top, mems = _need(name, i)
    i = int(i)
    m, z = mems[i]
    if z.dim() != 5 or int(z.shape[3]) != int(z.shape[4]):
        raise RuntimeError(_T('❌ コマを足せるのは正方形の Stack の素材だけです（画像は新しい素材として足してください）'))
    if str(m.get("mode") or "") == "training":
        raise RuntimeError(_T('❌ pool 型の素材にはコマを足せません'))
    edge = int(z.shape[3]) * 16
    tmpd = os.path.join(_g("REFMOD_STACK_DIR"), "_add")
    os.makedirs(tmpd, exist_ok=True)
    ups = []
    for j, p in enumerate(paths):                                 # 小さい絵は先に拡大（そろえる処理は素材より大きくしないため）
        with Image.open(p) as im:
            im = im.convert("RGB")
            if min(im.size) < edge:
                k = edge / float(min(im.size))
                im = im.resize((math.ceil(im.width * k), math.ceil(im.height * k)), Image.LANCZOS)
            q = os.path.join(tmpd, f"up_{j}.png")
            im.save(q)
            ups.append(q)
    sq, _e = _g("_refmod_stack_prepare")(ups, f"e{edge}")
    nf = _enc_ready()
    rb = {k: [] for k in _g("REF_KINDS")}
    rb["image"] = list(sq)
    res = _g("refmod_encode_refs")(rb, nf, short_edge=edge)
    zs = [zz for k, zz in res if k == "image"]
    if len(zs) != len(sq) or any(tuple(zz.shape[3:]) != tuple(z.shape[3:]) for zz in zs):
        raise RuntimeError(_T('❌ 足すコマの大きさが合いませんでした'))
    _backup(name)
    t0 = int(z.shape[2])
    mems[i] = (m, torch.cat([z] + [zz.to(z.dtype) for zz in zs], dim=2).contiguous())
    _write_raw(name, hdr, key, top, mems)
    os.makedirs(_td(), exist_ok=True)
    for j, q in enumerate(sq):                                    # コマの絵は揃えた絵から（VAE で戻すより正確）
        with Image.open(q) as im:
            im = im.convert("RGB")
            im.thumbnail((FRAME_SIDE, FRAME_SIDE), Image.LANCZOS)
            im.save(_fpath(name, i, t0 + j), quality=85)
    return _T('＋ 素材 {v0} にコマを {v1} 枚足しました（{v2} → {v3}）', v0=f'{i + 1}', v1=f'{len(zs)}',
              v2=f'{t0}', v3=f'{t0 + len(zs)}')


def members_add(name, paths):
    """画像・動画・音声を新しい素材として後ろに足す。大きさは今の映像の素材の短辺にそろえる（無ければ保存の既定）"""
    hdr, key, top, mems = _need(name)
    rb = {k: [] for k in _g("REF_KINDS")}
    for p in paths:
        rb[_kind_of(p)].append(p)
    short = [min(int(zz.shape[3]), int(zz.shape[4])) * 16 for _m, zz in mems if zz.dim() == 5]
    size = (f"e{max(256, max(short) // 32 * 32)}" if short
            else str(_ST["ctx"].g.get("REFMOD_SIZE_DEFAULT", "e768")))
    nf = _enc_ready()
    items, _pool = _g("refmod_encode_sized")(rb, nf, size)
    if not items:
        raise RuntimeError(_T('❌ 足す素材をエンコードできませんでした'))
    if len(mems) + len(items) > 256:
        raise RuntimeError(_T('❌ 素材が 256 件を超えます'))
    _backup(name)
    n0 = len(mems)
    leaf = name.split("/")[-1]
    add = []
    for k, (kind, z) in enumerate(items):
        add.append(({"name": f"{leaf}_{n0 + k + 1}", "kind": kind, "mode": "encode", "source": "h3-webui",
                     "source_shape": "", "pool": "" if kind == "audio" else "full-res", "optimize_steps": 0,
                     "tags": [], "description": "", "concept_type": "voice" if kind == "audio" else "generic",
                     "_format_version": 4, "sample_rate": 32000}, z))
    _write_raw(name, hdr, key, top, mems + add)
    srcs = [p for kk in ("image", "video", "audio") for p in rb[kk]]   # エンコードの並び（画像→動画→音声）
    for k, p in enumerate(srcs):
        if _kind_of(p) != "audio":
            try:
                _g("_refmod_save_one")(p, name, n0 + k)                 # 一覧の絵・プロンプト補助の見本（本体と同じ作り）
            except Exception:                                     # noqa: BLE001
                pass
    return _T('＋ 素材を {v0} 件足しました', v0=f'{len(add)}')


def members_remove(name, idxs):
    """素材をまとめて外す（最後の 1 件は残す）"""
    hdr, key, top, mems = _need(name)
    gone = sorted({int(x) for x in idxs if 0 <= int(x) < len(mems)})
    if not gone:
        raise RuntimeError(_T('❌ 素材を選んでください'))
    if len(gone) >= len(mems):
        raise RuntimeError(_T('❌ 最後の 1 件は外せません（RefMod ごと消すときは「🗑 選択中の RefMod を削除」）'))
    _backup(name)
    order = [k for k in range(len(mems)) if k not in gone]
    _write_raw(name, hdr, key, top, [mems[k] for k in order])
    _pics_reorder(name, order)
    return _T('✕ 素材 {v0} を外しました', v0=", ".join(str(k + 1) for k in gone))


# ---- 🆕 1.2.0 動画のコマを絵にする（STATUS にコマ番と並べる）。潜在を VAE で 1 コマずつ戻して小さな絵で控える。
#      Stack（画像を束ねた動画）は 1 コマ＝1 枚の画像なので、そのまま元の絵に近いものが出る。
#      ふつうの動画の素材は時間方向に圧縮されているため、2 コマ目以降はぼやけた目安になる
FRAME_SIDE = 160


def frames_missing(name):
    """コマの絵が足りない (素材の番号, コマ数) の並び"""
    try:
        items = _g("refmod_load")(name)[0]
    except Exception:                                             # noqa: BLE001
        return []
    return [(i, int(z.shape[2])) for i, (k, z) in enumerate(items)
            if k != "audio" and z.dim() == 5 and int(z.shape[2]) > 1
            and not all(os.path.isfile(_fpath(name, i, t)) for t in range(int(z.shape[2])))]


def frames_ensure(name):
    """足りないコマの絵を作る。生成中・モデル未読み込みなら何もしない → 作った枚数"""
    import torch
    from PIL import Image
    todo = frames_missing(name) if name else []
    if not todo or _g("_BUSY").is_set():
        return 0
    pipe = _ST["ctx"].g.get("pipe")
    vae = getattr(pipe, "vae", None)
    if vae is None:
        return 0
    items = _g("refmod_load")(name)[0]
    dev = next(vae.parameters()).device
    dt = next(vae.parameters()).dtype
    lm = torch.tensor(vae.config.latents_mean, device=dev).view(1, -1, 1, 1, 1)
    ls = torch.tensor(vae.config.latents_std, device=dev).view(1, -1, 1, 1, 1)
    pm = torch.tensor(pipe.pixel_mean, device=dev).view(1, -1, 1, 1, 1)
    ps = torch.tensor(pipe.pixel_std, device=dev).view(1, -1, 1, 1, 1)
    os.makedirs(_td(), exist_ok=True)
    made = 0
    with torch.inference_mode():
        for i, t in todo:
            z = items[i][1]
            for k in range(t):
                p = _fpath(name, i, k)
                if os.path.isfile(p):
                    continue
                if _g("_BUSY").is_set():                          # 途中で生成が始まったらやめる（残りは次に選んだとき）
                    return made
                zk = z[:, :, k:k + 1].to(dev, torch.float32) * ls + lm
                x = vae.decode(zk.to(dt), return_dict=False)[0].float()
                x = (x * ps + pm).clamp(0, 1)[0, :, 0]                # [3, H, W]
                im = Image.fromarray((x.permute(1, 2, 0).cpu().numpy() * 255).round().astype("uint8"))
                im.thumbnail((FRAME_SIDE, FRAME_SIDE), Image.LANCZOS)
                im.save(p, quality=85)
                made += 1
    try:
        torch.cuda.empty_cache()
    except Exception:                                             # noqa: BLE001
        pass
    return made


def _furi(p):
    import base64
    with open(p, "rb") as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode("ascii")


def hook_detail_html(name, items):
    """STATUS に足す HTML（🆕 1.3.0）: 素材の並び（本体の素材の並びの代わり）と、Stack の素材ごとのコマの並び。
    どちらも クリックで選ぶ → 🗑／枠の外へドラッグで消す、ファイルのドロップ／＋で足す（FRAME_JS）"""
    import html as _html
    esc = _html.escape
    hint = esc(_T('クリックで選択 → 🗑 か枠の外へドラッグで削除／ファイルをドロップで追加'))
    trash = f'<button type="button" class="rmm-d-trash" disabled title="{esc(_T("選んだものを消す"))}">🗑</button>'
    add_t = f'<div class="rmm-it rmm-add" title="{esc(_T("ファイルを選んで足す"))}">＋</div>'
    kname = {"image": _T("画像"), "video": _T("動画"), "audio": _T("音声")}
    tiles = []
    for i, (k, z) in enumerate(items or []):
        uri = _g("_refmod_thumb_uri")(name, i) if k != "audio" else ""
        pic = (f'<img src="{uri}" alt="" draggable="false">' if uri
               else f'<span class="rmm-it-icon">{_g("REFMOD_ICON").get(k, "🎞")}</span>')
        cap = f'{kname.get(k, k)} {_g("_rm_size")(k, z)}'
        tiles.append(f'<div class="rmm-it rmm-mem" data-i="{i}" title="{esc(cap)}">{pic}'
                     f'<span class="rmm-it-no">{i + 1}</span><span class="rmm-it-cap">{esc(cap)}</span></div>')
    out = [f'<div class="rmm-d-sec" data-sec="m" data-m=""><div class="rmm-d-shead">'
           f'<span class="rmm-d-stitle">{esc(_T("素材（{v0}）", v0=f"{len(items or [])}"))}</span>'
           f'<span class="rmm-d-hint">{hint}</span>{trash}</div>'
           f'<div class="rmm-d-strip">{"".join(tiles)}{add_t}</div></div>']
    for i, (k, z) in enumerate(items or []):
        if k == "audio" or z.dim() != 5 or int(z.shape[2]) <= 1:
            continue
        t = int(z.shape[2])
        fts = []
        for f in range(t):
            p = _fpath(name, i, f)
            pic = f'<img src="{_furi(p)}" alt="" draggable="false">' if os.path.isfile(p) else '<span class="rmm-f-none"></span>'
            fts.append(f'<div class="rmm-it rmm-fr" data-i="{f}">{pic}<span class="rmm-it-no">{f + 1}</span></div>')
        can_add = int(z.shape[3]) == int(z.shape[4])
        out.append(f'<div class="rmm-d-sec" data-sec="f" data-m="{i}"><div class="rmm-d-shead">'
                   f'<span class="rmm-d-stitle">{esc(_T("素材 {v0} のコマ（{v1}）", v0=f"{i + 1}", v1=f"{t}"))}</span>'
                   f'{trash}</div><div class="rmm-d-strip">{"".join(fts)}{add_t if can_add else ""}</div></div>')
    return "".join(out)


# ---- 🆕 1.3.0 STATUS の上の操作（JS → 隠し欄）。🔴 隠し欄は visible=False だと JS から触れないので CSS で隠す
FRAME_JS = r"""() => {
  if (window.__h3RmmFr) { return; }
  window.__h3RmmFr = true;
  const ROOT = '#rmm-detail';
  function send(v) {
    const box = document.querySelector('#rmm-fr-act textarea, #rmm-fr-act input');
    if (!box) { return; }
    window.__h3RmmFrSeq = (window.__h3RmmFrSeq || 0) + 1;
    box.value = v + '|' + window.__h3RmmFrSeq;
    box.dispatchEvent(new Event('input', {bubbles: true}));
  }
  function target(sec) {
    return (sec && sec.dataset.sec === 'f') ? ('f|' + sec.dataset.m) : 'm|';
  }
  function upload(files, sec) {
    if (!files || !files.length) { return; }
    const t = document.querySelector('#rmm-fr-target textarea, #rmm-fr-target input');
    const inp = document.querySelector('#rmm-fr-file input[type=file]');
    if (!t || !inp) { return; }
    window.__h3RmmFrSeq = (window.__h3RmmFrSeq || 0) + 1;
    t.value = target(sec) + '|' + window.__h3RmmFrSeq;
    t.dispatchEvent(new Event('input', {bubbles: true}));
    const dt = new DataTransfer();
    for (const f of files) { dt.items.add(f); }
    setTimeout(() => { inp.files = dt.files; inp.dispatchEvent(new Event('change', {bubbles: true})); }, 60);
  }
  function selIds(sec) {
    return [...sec.querySelectorAll('.rmm-it.sel:not(.rmm-add)')].map(e => e.dataset.i);
  }
  function refresh(sec) {
    const b = sec.querySelector('.rmm-d-trash');
    if (b) { b.disabled = !selIds(sec).length; }
  }
  function del(sec, ids) {
    if (!ids.length) { return; }
    sec.querySelectorAll('.rmm-it').forEach(e => { if (ids.includes(e.dataset.i) && !e.classList.contains('rmm-add')) { e.classList.add('gone'); } });
    send('del|' + sec.dataset.sec + '|' + sec.dataset.m + '|' + ids.join(','));
  }
  document.addEventListener('click', (e) => {
    const t = e.target; if (!t || !t.closest || !t.closest(ROOT)) { return; }
    const sec = t.closest('.rmm-d-sec'); if (!sec) { return; }
    if (t.closest('.rmm-d-trash')) { e.preventDefault(); del(sec, selIds(sec)); return; }
    const add = t.closest('.rmm-add');
    if (add) {
      e.preventDefault();
      const fi = document.createElement('input'); fi.type = 'file'; fi.multiple = true;
      fi.accept = sec.dataset.sec === 'f' ? 'image/*' : 'image/*,video/*,audio/*';
      fi.onchange = () => upload(fi.files, sec); fi.click(); return;
    }
    const it = t.closest('.rmm-it');
    if (it && !window.__h3RmmFrDragged) { it.classList.toggle('sel'); refresh(sec); }
  });
  // 枠の外へドラッグで消す（キーフレームと同じ: 外に出ると薄くなり、離すと消える）
  let drag = null;
  document.addEventListener('pointerdown', (e) => {
    const it = e.target && e.target.closest && e.target.closest(ROOT + ' .rmm-it:not(.rmm-add)');
    if (!it || e.button !== 0) { return; }
    drag = {it: it, sec: it.closest('.rmm-d-sec'), x0: e.clientX, y0: e.clientY, moved: false, out: false, ghost: null};
    window.__h3RmmFrDragged = false;
  });
  document.addEventListener('pointermove', (e) => {
    if (!drag) { return; }
    if (!drag.moved && Math.hypot(e.clientX - drag.x0, e.clientY - drag.y0) < 5) { return; }
    if (!drag.moved) {
      drag.moved = true; window.__h3RmmFrDragged = true;
      const g = drag.it.cloneNode(true); g.classList.add('rmm-ghost'); document.body.appendChild(g); drag.ghost = g;
      drag.it.classList.add('dragging');
    }
    drag.ghost.style.left = (e.clientX - 28) + 'px'; drag.ghost.style.top = (e.clientY - 28) + 'px';
    const r = drag.sec.querySelector('.rmm-d-strip').getBoundingClientRect();
    const out = e.clientX < r.left - 24 || e.clientX > r.right + 24 || e.clientY < r.top - 24 || e.clientY > r.bottom + 24;
    if (out !== drag.out) { drag.out = out; drag.ghost.classList.toggle('out', out); drag.it.classList.toggle('out', out); }
  });
  function endDrag() {
    if (!drag) { return; }
    const d = drag; drag = null;
    if (d.ghost) { d.ghost.remove(); }
    d.it.classList.remove('dragging', 'out');
    if (d.moved && d.out) {
      const ids = d.it.classList.contains('sel') ? selIds(d.sec) : [d.it.dataset.i];
      del(d.sec, ids);
    }
    setTimeout(() => { window.__h3RmmFrDragged = false; }, 0);
  }
  document.addEventListener('pointerup', endDrag);
  document.addEventListener('pointercancel', endDrag);
  // ファイルのドロップ（コマの並びの上＝コマ、それ以外の STATUS の中身＝新しい素材）
  function hasFiles(e) { return e.dataTransfer && [...(e.dataTransfer.types || [])].includes('Files'); }
  document.addEventListener('dragover', (e) => {
    const root = e.target && e.target.closest && e.target.closest(ROOT);
    document.querySelectorAll(ROOT + ' .rmm-d-sec.over').forEach(n => n.classList.remove('over'));
    if (!root || !hasFiles(e)) { return; }
    e.preventDefault();
    const sec = e.target.closest('.rmm-d-sec') || root.querySelector('.rmm-d-sec[data-sec="m"]');
    if (sec) { sec.classList.add('over'); }
  });
  document.addEventListener('dragleave', (e) => {
    if (e.target && e.target.closest && !e.target.closest(ROOT)) {
      document.querySelectorAll(ROOT + ' .rmm-d-sec.over').forEach(n => n.classList.remove('over'));
    }
  });
  document.addEventListener('drop', (e) => {
    const root = e.target && e.target.closest && e.target.closest(ROOT);
    if (!root || !hasFiles(e)) { return; }
    e.preventDefault();
    document.querySelectorAll(ROOT + ' .rmm-d-sec.over').forEach(n => n.classList.remove('over'));
    const sec = e.target.closest('.rmm-d-sec') || root.querySelector('.rmm-d-sec[data-sec="m"]');
    upload(e.dataTransfer.files, sec);
  });
}"""


def _fr_target(v):
    p = str(v or "").split("|")
    return (p[0], p[1] if len(p) > 1 else "")


def fr_delete(name, payload):
    """JS からの 'del|f|<素材>|<コマ,…>|連番' / 'del|m||<素材,…>|連番'"""
    p = str(payload or "").split("|")
    if len(p) < 4 or p[0] != "del":
        return None
    ids = [int(x) for x in p[3].split(",") if x.strip().lstrip("-").isdigit()]
    if p[1] == "f":
        i = int(p[2])
        t = int(_read_raw(name)[3][i][1].shape[2])
        return frames_drop(name, i, [k + 1 for k in ids if 0 <= k < t])
    return members_remove(name, ids)


def fr_upload(name, target, files):
    """ドロップ・＋で入ったファイル。コマの並び（f|i）なら画像はコマ、動画・音声は新しい素材"""
    paths = [f if isinstance(f, str) else getattr(f, "name", None) for f in (files or [])]
    paths = [p for p in paths if p and os.path.isfile(p)]
    if not name:
        raise RuntimeError(_T('❌ RefMod を 1 件選んでください'))
    if not paths:
        return None
    kind, m = _fr_target(target)
    msgs = []
    imgs = [p for p in paths if _kind_of(p) == "image"]
    rest = [p for p in paths if _kind_of(p) != "image"]
    if kind == "f" and m.isdigit() and imgs:
        msgs.append(frames_add(name, int(m), imgs))
        if rest:
            msgs.append(members_add(name, rest))
    else:
        msgs.append(members_add(name, paths))
    return "\n\n".join(msgs)


# ---------------------------------------------------------------- 本体のフック
def hook_after_save(name, items, paths, source="refs"):
    """RefMod を保存した直後（source: "refs"＝Reference タブ / "builder"＝BUILDER）。STATUS に足す行を返す（無ければ空）"""
    if not _ST["on_save"].get(source, DESC_ON_SAVE_DEFAULT) or not _g("llm_available")() or not any(k != "audio" for k, _z in items):
        return ""
    try:
        ap, of, notes = describe(paths, name)
        if ap or of:
            desc_set(name, ap, of)
        return "\n\n".join([_T('📝 見た目の説明を付けました（FINDER で直せます）: {v0}', v0=ap or "—")] + notes)
    except Exception as e:                                        # noqa: BLE001
        _log(_T('RefMod の説明を作れませんでした: {v0}', v0=f'{e}'))
        return _T('ℹ️ 見た目の説明は付けませんでした（{v0}）', v0=f'{e}')


def hook_prompt(t, refs_by_kind=None):
    """プロンプトの展開（本体の `@` 記法の直後、`<RefMod N>` の展開の前）。→ (文, STATUS に出す ⚠️ の行)"""
    notes = []
    auto = bool(_ST["auto"])
    # 1.0.3: 何を見て判断したかを 1 行ログに（自動挿入が効かないときの切り分け用。STATUS には出さない）
    _bare = [int(m.group(2)) for m in _REFMOD_BARE_RE.finditer(t)]
    if _bare or _PROMPT_TAG_RE.search(t):
        sel0 = list(_g("_REFMOD").get("sel") or [])
        _log(_T('ℹ️ 見た目の説明の自動挿入: {v0} ／ 選択中の RefMod {v1} ／ 文末のラベル {v2}',
                v0=("ON" if auto else "OFF"), v1=(", ".join(f"{i}={nm}" for i, nm in enumerate(sel0, 1)) or "—"),
                v2=(", ".join(f"<RefMod {n}>" for n in _bare) or "—")))
    if not (_PROMPT_TAG_RE.search(t) or (auto and _REFMOD_BARE_RE.search(t))):
        return t, notes
    sel = list(_g("_REFMOD").get("sel") or [])
    used = {int(x) for x in _PROMPT_TAG_RE.findall(t)}
    if auto:
        def _auto(m):
            n = int(m.group(2))
            if n in used or not (1 <= n <= len(sel)):
                return m.group(0)
            ap = desc_get(sel[n - 1])["appearance"]
            if not ap:
                # 1.0.2: 足さなかった理由をログに残す（STATUS には出さない＝⚠️ だけの約束）
                _log(_T('ℹ️ <RefMod {v0}>（{v1}）には見た目の説明が無いので足しませんでした（FINDER で付けられます）',
                        v0=f'{n}', v1=sel[n - 1]))
                return m.group(0)
            used.add(n)
            _log(_T('📝 <RefMod {v0}> に見た目の説明を足しました', v0=f'{n}'))
            return f"{m.group(1)}: {ap}"
        t = _REFMOD_BARE_RE.sub(_auto, t)
    nodesc = []

    def _psub(m):
        n = int(m.group(1))
        full = desc_full(desc_get(sel[n - 1])) if 1 <= n <= len(sel) else ""
        if not full:
            nodesc.append(n)
            return m.group(0)
        return full
    t = _PROMPT_TAG_RE.sub(_psub, t)
    for n in dict.fromkeys(nodesc):
        notes.append(_T('⚠️ <Prompt {v0}> に当たる説明がありません（RefMod {v0} が無いか、説明が付いていません）。そのまま残しました',
                        v0=f'{n}'))
    return t, notes


def hook_detail_rows(name, meta):
    """FINDER の STATUS に出す行 [(見出し, 値)]。🆕 1.2.0 見た目・服は STATUS の右の欄で直すので行には出さない。
    種類・タグ（generic・空なら出さない）と、見た目の説明として扱わない本家製の説明だけ"""
    try:
        ct, tags, _items = meta_info(name)
    except Exception:                                             # noqa: BLE001
        ct, tags = "generic", ""
    rows = []
    if ct and ct != "generic":
        rows.append((_T("種類"), _ctype_label(ct)))
    if tags:
        rows.append((_T("タグ"), tags))
    meta = meta or {}
    if (str(meta.get("description") or "").strip() and DESC_KEY not in meta
            and str(meta.get("concept_type") or "") != "identity"):
        rows.append((_T("説明"), str(meta["description"])))
    return rows


# ---------------------------------------------------------------- 本体が呼ぶ入口
def setup(ctx):
    _ST["ctx"] = ctx
    ctx.hook("prompt_pre", hook_prompt)
    ctx.hook("refmod_after_save", hook_after_save)
    ctx.hook("refmod_detail_rows", hook_detail_rows)
    ctx.hook("refmod_detail_html", hook_detail_html)              # 🆕 1.2.0 動画のコマ
    ctx.help("refmod", HELP["refmod"])


def build_slot(ctx, slot):
    """本体の UI の決まった場所（slot）で呼ばれる。その場所に部品を作る"""
    gr = ctx.gr
    ui = _ST["ui"]
    if slot == "refmod_save_opts":                                 # Reference タブ: 保存の下段（チェック｜ここ｜保存ボタン）
        ui["save_cb"] = gr.Checkbox(value=DESC_ON_SAVE_DEFAULT, label="見た目の説明も作る",
                                    scale=1, elem_id="refmod-desc-cb")
    elif slot == "rmb_opts":                                       # BUILDER: まとめるチェックの下
        ui["rmb_cb"] = gr.Checkbox(value=DESC_ON_SAVE_DEFAULT, label="見た目の説明も作る", elem_id="rmb-desc")
    elif slot == "refmod_bar2":                                    # CREATE ▸ RefMod: 検索〜Strength の箱の 2 段目
        ui["auto_cb"] = gr.Checkbox(value=AUTO_DESC_DEFAULT, label="見た目の説明を自動で足す",
                                    elem_id="refmod-auto-desc")
    elif slot == "rmm_status":                                     # 🆕 1.3.0 FINDER の STATUS の右: 編集をタブで切り替え
        with gr.Tabs(elem_id="rmm-ed-tabs"):
            with gr.Tab("見た目・服", id="rmm-ed-t-desc"):
                ui["ap"] = gr.Textbox(label="見た目（髪・目・顔・目印）", lines=7, elem_id="rmm-desc-ap")
                ui["of"] = gr.Textbox(label="服（@prompt で使う。自動では足さない）", lines=4, elem_id="rmm-desc-of")
                with gr.Row(elem_id="rmm-desc-row"):
                    ui["gen"] = gr.Button("✍️ 説明を生成", min_width=60, elem_id="rmm-desc-gen-btn", elem_classes=["rmm-ed-btn"])
                    ui["save"] = gr.Button("💾 説明を保存", min_width=60, elem_id="rmm-desc-save-btn", elem_classes=["rmm-ed-btn"])
            with gr.Tab("素材", id="rmm-ed-t-mem"):
                ui["add"] = gr.Dropdown(choices=[], value=None, filterable=True, label="ほかの RefMod の素材を足す",
                                        elem_id="rmm-ed-add", elem_classes=["rmm-ed-dd"])
                ui["add_btn"] = gr.Button("＋ 足す", elem_id="rmm-ed-add-btn", elem_classes=["rmm-ed-btn"])
                ui["undo_btn"] = gr.Button("↩ 直前の編集を元に戻す", interactive=False, elem_id="rmm-ed-undo-btn",
                                           elem_classes=["rmm-ed-btn"])
                gr.Markdown("素材やコマは左の STATUS の上で直せます（クリックで選ぶ → 🗑 か枠の外へドラッグで消す／"
                            "画像・動画・音声をドロップするか ＋ で足す。Stack のコマの並びに画像を落とすとコマになります）。"
                            "中身（潜在）を書き換えるので、直前の 1 回だけ元に戻せます。", elem_id="rmm-ed-hint")
            with gr.Tab("種類・タグ", id="rmm-ed-t-meta"):
                ui["ct"] = gr.Dropdown(choices=[(_ctype_label(v), v) for v in CONCEPT_TYPES], value="generic",
                                       label="種類（concept_type）", elem_id="rmm-ed-ct", elem_classes=["rmm-ed-dd"])
                ui["tags"] = gr.Textbox(label="タグ（カンマ区切り）", elem_id="rmm-ed-tags")
                ui["meta_btn"] = gr.Button("💾 種類・タグを保存", elem_id="rmm-ed-meta-btn", elem_classes=["rmm-ed-btn"])
        # STATUS の上の操作の受け渡し口（CSS で隠す）
        ui["fr_act"] = gr.Textbox(value="", show_label=False, container=False, elem_id="rmm-fr-act")
        ui["fr_target"] = gr.Textbox(value="", show_label=False, container=False, elem_id="rmm-fr-target")
        ui["fr_file"] = gr.File(file_count="multiple", show_label=False, elem_id="rmm-fr-file")


def _set_on_save_refs(v):
    _ST["on_save"]["refs"] = bool(v)


def _set_on_save_builder(v):
    _ST["on_save"]["builder"] = bool(v)


def _set_auto(v):
    _ST["auto"] = bool(v)


def _load(name):
    gr = _ST["ctx"].gr
    if not name:
        return gr.update(value=""), gr.update(value="")
    d = desc_get(name)
    return gr.update(value=d["appearance"]), gr.update(value=d["outfit"])


def _write(name):
    gr = _ST["ctx"].gr
    if not name:
        return gr.update(), gr.update(), _T('❌ RefMod を 1 件選んでください')
    if _g("_BUSY").is_set():
        return gr.update(), gr.update(), _T('⏳ 生成中は使えません。終わってからもう一度押してください')
    try:
        ap, of, notes = describe(desc_sources(name), name)
    except Exception as e:                                        # noqa: BLE001
        return gr.update(), gr.update(), _T('❌ 書けませんでした: {v0}', v0=f'{e}')
    return gr.update(value=ap), gr.update(value=of), "\n\n".join(
        [_T('✍️ 書きました。直してから「説明を保存」を押してください')] + notes)


def _save(name, appearance, outfit):
    if not name:
        return _T('❌ RefMod を 1 件選んでください'), ""
    detail = _g("rmm_detail_html")
    try:
        desc_set(name, appearance, outfit)
    except Exception as e:                                        # noqa: BLE001
        return _T('❌ 説明を保存できませんでした: {v0}', v0=f'{e}'), detail(name)
    done = (_T('💾 説明を保存しました: {v0}', v0=name) if (str(appearance or "").strip() or str(outfit or "").strip())
            else _T('🗑 説明を消しました: {v0}', v0=name))
    return done, detail(name)


# ---- 🆕 1.1.0 編集パネルの配線用
def _ed_view(name):
    """編集欄の中身 (種類, タグ, 足す候補, 元に戻す)"""
    gr = _ST["ctx"].gr
    others = [n for n in _g("refmod_choices")() if n != name]
    if not name:
        return (gr.update(value="generic"), gr.update(value=""), gr.update(choices=others, value=None),
                gr.update(interactive=False))
    try:
        ct, tags, _items = meta_info(name)
    except Exception:                                             # noqa: BLE001
        ct, tags = "generic", ""
    return (gr.update(value=ct if ct in CONCEPT_TYPES else "generic"), gr.update(value=tags),
            gr.update(choices=others, value=None), gr.update(interactive=has_backup(name)))


def _ed_load(name):
    return _ed_view(name)


def _frames_job(name):
    """選んだあと・素材を足したあと: 足りないコマの絵を作って STATUS を描き直す（作るものが無ければ送らない）"""
    gr = _ST["ctx"].gr
    try:
        if name and frames_ensure(name):
            return gr.update(value=_g("rmm_detail_html")(name))
    except Exception as e:                                        # noqa: BLE001
        _log(_T('コマの絵を作れませんでした: {v0}', v0=f'{e}'))
    return gr.update()


def _ed_run(fn, name, *args):
    """操作を走らせて (STATUS の文, 詳細の HTML, 編集欄の中身…) を返す"""
    try:
        if not name:
            raise RuntimeError(_T('❌ RefMod を 1 件選んでください'))
        msg = fn(name, *args)
        if msg is None:
            msg = _T('変更はありません')
    except Exception as e:                                        # noqa: BLE001
        msg = f"{e}" if str(e).startswith(("❌", "⏳")) else _T('❌ 編集できませんでした: {v0}', v0=f'{e}')
    detail = _g("rmm_detail_html")(name) if name else ""
    return (msg, detail) + tuple(_ed_view(name))


def _ed_meta(name, ct, tags):
    return _ed_run(lambda n: set_meta(n, ct, tags), name)


def _ed_add(name, other):
    return _ed_run(lambda n: mem_add(n, other)[0], name)


def _ed_undo(name):
    def _u(n):
        undo(n)
        return _T('↩ 直前の編集を元に戻しました: {v0}', v0=n)
    return _ed_run(_u, name)


def _fr_act(name, payload):
    return _ed_run(lambda n: fr_delete(n, payload), name)


def _fr_upload(name, target, files):
    gr = _ST["ctx"].gr
    return _ed_run(lambda n: fr_upload(n, target, files), name) + (gr.update(value=None),)


def wire(ctx, comps):
    """部品を作り終えたあとに呼ばれる。comps は本体の部品（rmm_sel / rmm_msg / rmm_detail）"""
    ui = _ST["ui"]
    if "save_cb" in ui:
        ui["save_cb"].change(fn=_set_on_save_refs, inputs=[ui["save_cb"]], outputs=None, queue=False, show_progress="hidden")
    if "rmb_cb" in ui:
        ui["rmb_cb"].change(fn=_set_on_save_builder, inputs=[ui["rmb_cb"]], outputs=None, queue=False, show_progress="hidden")
    if "auto_cb" in ui:
        ui["auto_cb"].change(fn=_set_auto, inputs=[ui["auto_cb"]], outputs=None, queue=False, show_progress="hidden")
    if "ap" in ui and "rmm_sel" in comps:
        sel = comps["rmm_sel"]
        # 1.0.3: gr.State の .change は実機で飛ばなかった → 本体の選択イベント（rmm_pick_events）に .then でつなぐ
        evs = list(comps.get("rmm_pick_events") or [])
        if evs:
            for ev in evs:
                ev.then(fn=_load, inputs=[sel], outputs=[ui["ap"], ui["of"]], queue=False, show_progress="hidden")
        else:
            sel.change(fn=_load, inputs=[sel], outputs=[ui["ap"], ui["of"]], queue=False, show_progress="hidden")
        # ✍️ はテキストエンコーダ（GPU）を使うので、生成と同じキューに並べる
        ui["gen"].click(fn=_write, inputs=[sel], outputs=[ui["ap"], ui["of"], comps["rmm_msg"]],
                        show_progress="minimal", concurrency_id="generate")
        ui["save"].click(fn=_save, inputs=[sel, ui["ap"], ui["of"]], outputs=[comps["rmm_msg"], comps["rmm_detail"]],
                         queue=False, show_progress="hidden")
    if "ct" in ui and "rmm_sel" in comps:
        sel = comps["rmm_sel"]
        det = comps["rmm_detail"]
        ed_out = [ui["ct"], ui["tags"], ui["add"], ui["undo_btn"]]
        evs = list(comps.get("rmm_pick_events") or [])
        for ev in evs or []:
            ev.then(fn=_ed_load, inputs=[sel], outputs=ed_out, queue=False, show_progress="hidden").then(
                fn=_frames_job, inputs=[sel], outputs=[det], show_progress="hidden")
        if not evs:
            sel.change(fn=_ed_load, inputs=[sel], outputs=ed_out, queue=False, show_progress="hidden")
        outs = [comps["rmm_msg"], det] + ed_out
        # 潜在を書き換えたあとは FINDER の一覧（絵・参照の数）と CREATE の選択欄も描き直す（本体の関数を借りる）
        ref_in, ref_out = comps.get("rmm_refresh_in"), comps.get("rmm_refresh_out")
        dd_out = comps.get("refmod_dd_out")

        def _chain(ev):
            ev = ev.then(fn=_frames_job, inputs=[sel], outputs=[det], show_progress="hidden")
            if ref_in is not None and ref_out is not None:
                ev = ev.then(fn=_g("render_refmods"), inputs=ref_in, outputs=ref_out, queue=False, show_progress="hidden")
            if dd_out is not None:
                ev = ev.then(fn=_g("refmod_dd_sync"), outputs=dd_out, queue=False, show_progress="hidden")
            return ev
        ui["meta_btn"].click(fn=_ed_meta, inputs=[sel, ui["ct"], ui["tags"]], outputs=outs,
                             queue=False, show_progress="hidden")
        _chain(ui["add_btn"].click(fn=_ed_add, inputs=[sel, ui["add"]], outputs=outs, show_progress="minimal"))
        _chain(ui["undo_btn"].click(fn=_ed_undo, inputs=[sel], outputs=outs, show_progress="minimal"))
        # STATUS の上の操作（JS → 隠し欄は必ず .change＝本体 #257 と同じ。.input は飛ばない）。
        # 足すのはエンコード（GPU）なので生成と同じ列に並べる
        _chain(ui["fr_act"].change(fn=_fr_act, inputs=[sel, ui["fr_act"]], outputs=outs, show_progress="minimal"))
        _chain(ui["fr_file"].upload(fn=_fr_upload, inputs=[sel, ui["fr_target"], ui["fr_file"]],
                                    outputs=outs + [ui["fr_file"]], show_progress="minimal", concurrency_id="generate"))
        demo = comps.get("demo")
        if demo is not None:
            demo.load(fn=None, js=FRAME_JS)
