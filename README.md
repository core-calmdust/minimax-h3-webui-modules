# MiniMax H3 WebUI — extension modules

Optional feature modules for **MiniMax H3 WebUI on Google Colab (note edition)**.
The WebUI's core (notebook cells 1–3) loads modules from this repository at a
**pinned commit** and calls them; the modules depend on the core and do not run
on their own.

- License: **Apache-2.0** for everything in this repository (see `LICENSE`, `NOTICE`).
- The core WebUI is distributed separately and is **not** covered by this license.
- No model weights are stored here. MiniMax H3 is governed by the MiniMax H3
  Community License Agreement.
- Unofficial community project, not affiliated with MiniMax.

## Modules

| module | since | what it does |
|---|---|---|
| `modules/refmod_tools.py` | WebUI ver1.7 | RefMod appearance descriptions: written by Prompt Assist on save / in FINDER, added to `<Subject k> is @refmod N.` automatically, `<Subject k> is @character N.` (label + appearance + outfit; `@prompt N` = description only) for the full text; FINDER STATUS: tabs for appearance / outfit, sources (add from another RefMod, one-step undo) and type / tags; sources and Stack frames edited directly in STATUS (click to select, 🗑 or drag out to remove, drop images / videos / audio to add with a progress bar, drag to reorder; long Stacks scroll in two rows with frame thumbnails made progressively) |
| `modules/face_refiner.py` | WebUI ver1.7 | Face Refiner: tracks faces (OpenCV Zoo YuNet), redraws the face clip with MiniMax H3 and pastes it back (CREATE option and UPSCALE ▸ Face Refiner). The UI stays in the core |
| `modules/spark_attn.py` | WebUI ver1.7 | Speed-up "Spark (quality first)" / "Fast Spark (balanced)": fetches Spark-H3 (zechengtang/Spark-H3, Apache-2.0) at a pinned commit at first use and runs the generation with its block-sparse attention; keeps the Triton kernel cache on Google Drive (only when Drive is connected). The selector stays in the core |
| `modules/character_guide.py` | WebUI ver1.7 | Character Guide for long videos (Motion Context): picks a good face frame from segment 1 and uses it as the R2V reference for later segments (T2V only), matches the brightness of the frames handed to the next segment (multiplicative, colors untouched), and softens over-sharp detail inside the last DiT blocks (Detail & Contrast, idea from Fizgig H3 Tweaks / MIT, own code). Face detection: OpenCV Zoo YuNet (Apache-2.0). The switch and the SYSTEM card are built through slots |
| `modules/ref_filters.py` | WebUI ver1.7 | LIBRARY: convert the selected video / still for use as a reference in other generators and download it in one click — Blocking (3-tone grey), Blocking (person only, background removed with torchvision DeepLabV3), line art (XDoG), depth map (Video Depth Anything Small, Apache-2.0, fetched at a pinned commit/revision) |

## Translations (`i18n/`)

The WebUI core's UI text (cell 3) is translated here. The **Japanese source text is the key**; anything missing
falls back to Japanese.

- `i18n/manifest.json` lists the languages (`code`, `name`, `file`, `sha256`). The core pins this file by commit and
  sha256, and checks every language file against the sha256 written in the manifest.
- `i18n/cell3/<code>.json` maps Japanese source text → translation.
- **Adding a language**: add `i18n/cell3/<code>.json`, add one entry to `manifest.json` (with its sha256), then update
  `I18N_PIN` (commit and manifest sha256) in cell 3. The language selector is built from the manifest.
- Placeholders such as `{v0}` must be kept exactly. Modules keep their own strings in their `I18N` dict.

## CSS and JavaScript (`assets/`)

The WebUI core's stylesheet and browser scripts (cell 3) live here.
`assets/manifest.json` lists each file (`name`, `file`, `sha256`); the core pins the manifest by commit and sha256
(`ASSETS_PIN` in cell 3) and checks every file. `style.css` still contains placeholders such as `__FONT__`, which the
core fills in at start-up. If the assets cannot be fetched, the core starts with a minimal fallback stylesheet.

## Module contract (API 1)

The core fetches `https://raw.githubusercontent.com/core-calmdust/minimax-h3-webui-modules/<commit>/<path>`,
checks its **sha256** against the value pinned in cell 3, keeps a copy on Drive, and imports it.
If a module cannot be fetched or does not match, the WebUI starts without it.

Each module is a Python file under `modules/` that exposes:

| name | called by the core | purpose |
|---|---|---|
| `NAME`, `VERSION`, `API` | at load | `API` must equal the core's `MODULE_API` (currently 1) |
| `I18N` (dict) | at load | the module's own ja → en/zh/ko strings, merged into the core's table |
| `CSS` (str) | at launch | appended to the core's CSS (use the core's `--h3-*` variables) |
| `SLOTS` (tuple) | while building the UI | the places in the core UI where the module adds components |
| `setup(ctx)` | at load | register hooks: `ctx.hook(kind, fn)`, help text: `ctx.help(key, text)`, functions the core calls: `ctx.provide(name, fn)` |
| `build_slot(ctx, slot)` | inside the core's `gr.Blocks`, at each slot | create the module's Gradio components |
| `wire(ctx, comps)` | after the UI is built | connect events; `comps` holds core components |

`ctx.g` is the core's global namespace (the module borrows core functions through it), `ctx.T` translates,
`ctx.log` logs, `ctx.gr` is Gradio.

Hooks: `prompt_pre(text, refs) -> (text, warnings)` · `refmod_after_save(name, items, paths, source) -> str` ·
`refmod_detail_rows(name, meta) -> [(label, value)]`.
Slots: `refmod_save_opts` · `rmb_opts` · `refmod_bar2` · `rmm_right`.
Provided functions: `face_refine_apply` · `face_refine_still_img` · `do_video_refine` (face_refiner) · `spark_ctx` · `accel_sync` · `accel_first_note` (spark_attn) · `long_guide_session` (character_guide) · `ref_filter_convert` (ref_filters).

Modules must not copy code from the core.

---|---|---|
| `build_ui(ctx)` | inside the core's `gr.Blocks` | create the module's Gradio components |
| `wire(ctx, ui)` | after the UI is built | connect events |
| `I18N` (dict) | at load | the module's own ja/en/zh/ko strings |

`ctx` is provided by the core (translation function, state, pipeline access).
Modules must not copy code from the core.

---

### 日本語

MiniMax H3 WebUI（note版）の**拡張モジュール**置き場です。WebUI 本体（セル1〜3）が、このリポジトリを
**コミット固定**で読み込んで呼び出します。モジュールは本体に依存し、単体では動きません。

- このリポジトリの中身は **Apache-2.0**（`LICENSE` / `NOTICE`）。
- WebUI 本体は別配布で、このライセンスの対象ではありません。
- 本体はセル3に書いた**コミットと sha256** で固定して読み込み、Drive に控えを置きます。取れない・合わないときはモジュール無しで起動します。
- `assets/` は本体（セル3）の CSS と JS です（`manifest.json` が一覧。セル3の `ASSETS_PIN` で固定）。
- `i18n/` は本体（セル3）の画面の翻訳です（原文の日本語がキー。`manifest.json` が言語の一覧）。言語を足すときは `i18n/cell3/<言語>.json` と manifest の 1 行を足し、セル3の `I18N_PIN` を更新します。

| モジュール | 内容 |
|---|---|
| `modules/refmod_tools.py` | RefMod の見た目の説明（保存時・FINDER でプロンプト補助が書く／`<Subject k> is @refmod N.` に自動で足す／`<Subject k> is @character N.` でラベル＋全文（`@prompt N` は説明だけ））／FINDER の STATUS: 見た目・服／素材（ほかの RefMod から足す・元に戻す）／種類・タグのタブ、素材と Stack のコマは STATUS の上で直接（クリックで選ぶ・🗑 か枠外へドラッグで消す・画像／動画／音声のドロップで足す〔進み具合つき〕・ドラッグで並べ替え・長い Stack は 2 段でスクロール、コマの絵は少しずつ作る） |
| `modules/face_refiner.py` | Face Refiner（YuNet で顔を追跡 → H3 で顔のクリップを描き直して貼り戻す。CREATE の顔補正・UPSCALE ▸ Face Refiner。UI は本体） |
| `modules/spark_attn.py` | 高速化「Spark（画質優先）」「Fast Spark（バランス）」（初めて使うときに Spark-H3〔zechengtang/Spark-H3、Apache-2.0〕を版固定で取り寄せ、その疎 attention で生成する／Triton の組み立て結果を Google ドライブに控える〔Drive 連携時のみ〕。プルダウンは本体） |
| `modules/character_guide.py` | 長尺（Motion Context）の Character Guide（T2V では 1 本目から顔のよいコマを選び 2 本目以降の R2V の参照に／次へ渡すコマの明るさを掛け算で 1 本目に合わせる〔色は触らない〕／最後の DiT ブロックで細部の尖りを抑える Detail & Contrast〔Fizgig H3 Tweaks・MIT の考え方、自作〕。顔検出は OpenCV Zoo の YuNet〔Apache-2.0〕。スイッチと SYSTEM の箱は slot で作る） |
| `modules/ref_filters.py` | LIBRARY で選んだ動画・静止画を、ほかの生成 AI の参照向けに加工してそのままダウンロード（Blocking＝灰 3 階調／Blocking（人物）＝背景を除く〔torchvision DeepLabV3〕／線画〔XDoG〕／深度マップ〔Video Depth Anything Small・Apache-2.0、版固定で取り寄せ〕） |
- モデルの重みは置きません。非公式のコミュニティ製で、MiniMax とは関係ありません。
