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
メタ（本家 Luisacaotica/ComfyUI-MiniMaxH3Mod 互換）: `description`＝自然文、`concept_type`＝identity、
分け書きは独自キー `h3webui_desc`＝{"appearance", "outfit"}。bundle は全体に置く。潜在には触らない。
"""
import json
import os
import re

NAME = "refmod_tools"
VERSION = "1.0.0"
API = 1                                   # 本体の MODULE_API と一致しないと読み込まれない
SLOTS = ("refmod_save_opts", "rmb_opts", "refmod_bar2", "rmm_right")

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
    "服": {"en": "Outfit", "zh": "服装", "ko": "의상"},
    "見た目": {"en": "Appearance", "zh": "外貌", "ko": "외모"},
    "説明に使える絵がありません（画像・動画の素材か、WebUI で保存した RefMod の見本が要ります）": {"en": "No pictures to describe (needs image/video sources, or a RefMod saved in the WebUI with previews)", "zh": "没有可用于描述的图片（需要图片/视频素材，或在 WebUI 中保存的带预览的 RefMod）", "ko": "설명에 쓸 그림이 없습니다 (이미지·영상 소재나 WebUI에서 저장한 RefMod의 견본이 필요합니다)"},
    "💾 説明を保存しました: {v0}": {"en": "💾 Description saved: {v0}", "zh": "💾 已保存描述：{v0}", "ko": "💾 설명을 저장했습니다: {v0}"},
    "📝 <RefMod {v0}> に見た目の説明を足しました": {"en": "📝 Added the appearance description to <RefMod {v0}>", "zh": "📝 已为 <RefMod {v0}> 添加外貌描述", "ko": "📝 <RefMod {v0}>에 외모 설명을 붙였습니다"},
    "📝 見た目の説明を付けました（FINDER で直せます）: {v0}": {"en": "📝 Appearance description added (editable in FINDER): {v0}", "zh": "📝 已添加外貌描述（可在 FINDER 中修改）：{v0}", "ko": "📝 외모 설명을 붙였습니다 (FINDER에서 고칠 수 있습니다): {v0}"},
    "🗑 説明を消しました: {v0}": {"en": "🗑 Description removed: {v0}", "zh": "🗑 已删除描述：{v0}", "ko": "🗑 설명을 지웠습니다: {v0}"},
    "⏳ もう書いています": {"en": "⏳ Already writing", "zh": "⏳ 正在撰写中", "ko": "⏳ 이미 쓰는 중입니다"},
    "⏳ 生成中は使えません。終わってからもう一度押してください": {"en": "⏳ Not available while generating. Press again when it finishes", "zh": "⏳ 生成过程中无法使用。完成后请再按一次", "ko": "⏳ 생성 중에는 쓸 수 없습니다. 끝난 뒤 다시 눌러 주세요"},
    "❌ 書けませんでした: {v0}": {"en": "❌ Could not write it: {v0}", "zh": "❌ 无法撰写：{v0}", "ko": "❌ 쓰지 못했습니다: {v0}"},
    "服（@prompt で使う。自動では足さない）": {"en": "Outfit (used by @prompt; not added automatically)", "zh": "服装（用于 @prompt，不会自动添加）", "ko": "의상 (@prompt에서 사용. 자동으로는 붙이지 않음)"},
    "見た目の説明": {"en": "Appearance description", "zh": "外貌描述", "ko": "외모 설명"},
    "見た目の説明も作る": {"en": "Also write an appearance description", "zh": "同时生成外貌描述", "ko": "외모 설명도 만들기"},
    "見た目の説明を自動で足す": {"en": "Add the appearance description automatically", "zh": "自动添加外貌描述", "ko": "외모 설명을 자동으로 붙이기"},
    "見た目（髪・目・顔・目印）": {"en": "Appearance (hair, eyes, face, marks)", "zh": "外貌（头发、眼睛、脸、特征）", "ko": "외모 (머리·눈·얼굴·특징)"},
    "✍️ 説明を生成": {"en": "✍️ Generate description", "zh": "✍️ 生成描述", "ko": "✍️ 설명 생성"},
    "💾 説明を保存": {"en": "💾 Save description", "zh": "💾 保存描述", "ko": "💾 설명 저장"},
}

# 字・ボタンは本体の CSS 変数（--h3-*）に合わせる。チェックの字は本体の他のチェックと同じ 13px・text3、
# FINDER のボタンは「CREATE で使う」「変更する」と同じ見た目
CSS = """
/* ---- 拡張モジュール refmod_tools ---- */
#refmod-desc-cb label span, #refmod-desc-cb span, #rmb-desc label span, #rmb-desc span,
#refmod-auto-desc label span, #refmod-auto-desc span {
    font-size: 13px !important; color: var(--h3-text3) !important;
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
    """FINDER の STATUS に出す行 [(見出し, 値)]。説明があれば本体の『説明』の行の代わりに見た目・服を出す"""
    d = desc_get(name)
    rows = []
    if d["appearance"]:
        rows.append((_T("見た目"), d["appearance"]))
    if d["outfit"]:
        rows.append((_T("服"), d["outfit"]))
    return rows


# ---------------------------------------------------------------- 本体が呼ぶ入口
def setup(ctx):
    _ST["ctx"] = ctx
    ctx.hook("prompt_pre", hook_prompt)
    ctx.hook("refmod_after_save", hook_after_save)
    ctx.hook("refmod_detail_rows", hook_detail_rows)
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
    elif slot == "rmm_right":                                      # FINDER の右列: STATUS の下
        with gr.Accordion("見た目の説明", open=False, elem_classes=["panel-acc"]):
            ui["ap"] = gr.Textbox(label="見た目（髪・目・顔・目印）", lines=3, elem_id="rmm-desc-ap")
            ui["of"] = gr.Textbox(label="服（@prompt で使う。自動では足さない）", lines=2, elem_id="rmm-desc-of")
            ui["gen"] = gr.Button("✍️ 説明を生成", elem_id="rmm-desc-gen-btn")
            ui["save"] = gr.Button("💾 説明を保存", elem_id="rmm-desc-save-btn")


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
        sel.change(fn=_load, inputs=[sel], outputs=[ui["ap"], ui["of"]], queue=False, show_progress="hidden")
        # ✍️ はテキストエンコーダ（GPU）を使うので、生成と同じキューに並べる
        ui["gen"].click(fn=_write, inputs=[sel], outputs=[ui["ap"], ui["of"], comps["rmm_msg"]],
                        show_progress="minimal", concurrency_id="generate")
        ui["save"].click(fn=_save, inputs=[sel, ui["ap"], ui["of"]], outputs=[comps["rmm_msg"], comps["rmm_detail"]],
                         queue=False, show_progress="hidden")
