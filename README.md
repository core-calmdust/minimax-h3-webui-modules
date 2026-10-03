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

## Module contract (draft)

Each module is a Python file under `modules/` that exposes:

| function | called by the core | purpose |
|---|---|---|
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
- モデルの重みは置きません。非公式のコミュニティ製で、MiniMax とは関係ありません。
