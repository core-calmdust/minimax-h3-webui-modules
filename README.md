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
| `modules/refmod_tools.py` | WebUI ver1.7 | RefMod appearance descriptions: written by Prompt Assist on save / in FINDER, added to `<Subject k> is @refmod N.` automatically, `@prompt N` for the full text |

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
| `setup(ctx)` | at load | register hooks: `ctx.hook(kind, fn)`, help text: `ctx.help(key, text)` |
| `build_slot(ctx, slot)` | inside the core's `gr.Blocks`, at each slot | create the module's Gradio components |
| `wire(ctx, comps)` | after the UI is built | connect events; `comps` holds core components |

`ctx.g` is the core's global namespace (the module borrows core functions through it), `ctx.T` translates,
`ctx.log` logs, `ctx.gr` is Gradio.

Hooks: `prompt_pre(text, refs) -> (text, warnings)` · `refmod_after_save(name, items, paths, source) -> str` ·
`refmod_detail_rows(name, meta) -> [(label, value)]`.
Slots: `refmod_save_opts` · `rmb_opts` · `refmod_bar2` · `rmm_right`.

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

| モジュール | 内容 |
|---|---|
| `modules/refmod_tools.py` | RefMod の見た目の説明（保存時・FINDER でプロンプト補助が書く／`<Subject k> is @refmod N.` に自動で足す／`@prompt N` で全文） |
- モデルの重みは置きません。非公式のコミュニティ製で、MiniMax とは関係ありません。
