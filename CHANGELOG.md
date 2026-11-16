# 変更履歴

## 0.4.0（試作）

- エージェント向けのスキル `skills/kanzashi/SKILL.md`（英語は `SKILL.en.md`）と入口 `AGENTS.md`。髪の調整の流れと、ユーザーに確認する所を決めた。
- `scripts/kanzashi_run.py`：検出済みの髪は毛束を残して UV だけを作り直す。`--swap`（張り替え）、`--apply`（形の確定）、`--redetect`（検出のやり直し）を足した。UV の検査に落ちたときは終了コードが 1 になる。
- `scripts/kanzashi_preview.py`：毛束ごとの色の画像（前・後ろ・左・右と UV）を出す。
- `tools/install_addon.py`：アドオンが入っているかを調べる（`--check`）、ZIP を作って拡張機能として入れる。

English: a skill for agents (`skills/kanzashi/`), `kanzashi_run.py` keeps existing strands and gained `--swap`, `--apply`, `--redetect`; `kanzashi_preview.py` renders the strand colours; `tools/install_addon.py` checks and installs the add-on.

## 0.3.0（試作）

動きは変えずに、コードを整理した。

- モジュールを分けて名前を短くした（`panel`・`ops_hair`・`ops_paint`・`ops_bend`・`ops_uv`・`common`、`tree`・`edit`・`strand_uv`・`swap`・`strands`・`rewire`・`wire`・`i18n`）。パッケージの中は相対 import。
- オペレーターの名前を `lida.hs_*` から `kanzashi.*` にした。メッシュの属性（`lw_*`）、シーンの設定（`lida_hs_*`）、モディファイアやノードグループの名前は変えていないので、0.2 までに作ったファイルはそのまま続きができる。
- Blender の拡張機能の定義 `blender_manifest.toml` を足した。アドオンの ZIP は拡張機能として入る。
- 入れずにパネルを出す起動は `scripts/kanzashi_panel.py` に変わった（`kanzashi/panel.py` を直接は実行できない）。スクリプト版の ZIP は、パッケージ `kanzashi/` を丸ごと含む。
- 整理の前後で結果が同じかを比べる `tests/regress.py`・`tests/compare.py`。書き方は ruff で整えた（`ruff.toml`）。

English: no change in behaviour. The code was split into smaller modules with relative imports, the operators were renamed to `kanzashi.*` (data names in files are unchanged, so older files keep working), an extension manifest was added, and the panel without installing is now started by `scripts/kanzashi_panel.py`.

## 0.2.0（試作）

- パネルを日本語と英語で使えるようにした。いちばん上の欄で Auto／日本語／English を選ぶ（Auto は Blender の表示言語に合わせる）。
- 英語の説明 `README.en.md`。
- 英語の文の抜けと `%` の書式の食い違いを調べる `tools/check_i18n.py`。

English: the panel now works in Japanese and English (Auto / 日本語 / English at the top of the panel), with an English README.

## 0.1.0（試作）

- 毛束の検出、色の塗り直しによる付け替え、ワイヤーでの曲げ、毛束ごとの UV（検査・テクスチャ用の書き出し・張り替え・元に戻す）。
- アドオン（パネル）と、パネルなしで動かすスクリプト `scripts/kanzashi_run.py`。
- 配布用の ZIP を作る `tools/build_packages.py`。
