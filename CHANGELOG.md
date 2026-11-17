# 変更履歴

## 未リリース

- README（日本語・英語）：どういうアドオンか、何ができるかを図で説明した。図は `tools/make_figures.py` が描く模式図（`docs/fig_*.svg`）。実際の髪で撮った画像（パネルの画面、毛束ごとの色、曲げた例）も入れた。「使う順番」を、段ごとのパネルの画面つきの手順にした（`docs/step1〜6.ja.png`・`.en.png`）。
- スキル：工程の位置を決まりにした。頭と髪のパーツ分けの後、テクスチャを貼り直す前に行う。手順 0 で順番を確かめ、逆のときはユーザーに聞く。

English: the READMEs now explain with figures what the add-on is and what it does (`docs/fig_*.svg`, drawn by `tools/make_figures.py`); the skill now fixes the place in the pipeline (after the head and the hair are split into parts, before the textures are redone) and checks it in step 0.

## 0.4.1（試作）

- ③ と ④ は、どちらか片方だけが動くようにした。「色を直すモードに入る」を押すと、曲げている最中ならつまみを書き戻して消してから入る（逆向きは前からそうなっていた）。
- つまみの G（動かす）と R（回す）を、Kanzashi の操作にした（つまみを選んでいる間だけ。ほかの物の G・R は Blender のまま）。動かしている・回している最中も、中ボタンのドラッグとホイールで視点を変えられる。クリックで決定、右クリック・Esc で取り消し、X・Y・Z で軸、Shift でゆっくり。数値の入力はできない。
- つまみを R で回すと、その点でワイヤーの向きが変わり、毛束が付いてくる。回した点は、曲げ終わった後も向きを保つ（ハンドルを「整列」にして書き戻す）。動かしただけの点は、今までどおり自動でなめらかにする。
- 注意を足した：Tripo でテクスチャを作るとき、髪に Smart UV を使わない（UV が作り直されて、毛束ごとの UV が消える）。パネルの ⑤、書き出しの後のメッセージ、README、スキルに書いた。
- 毛束ごとの UV を作った髪に印（`kanzashi_uv_lock`）を付けるようにした。`scripts/kanzashi_guard.py` が、その髪が後から分割・結合・UV の作り直しをされていないかを調べる（終了コード 1 で知らせる）。パネルの ⑤ にも、UV を作った後に頂点・面が変わった髪を赤く出す。スキルに「UV を作った髪を、ほかの道具・スキルで分割・展開し直さない。触る前と後に検査する」を決まりとして足した。

English: a hair that got the strand UV is marked, and `scripts/kanzashi_guard.py` tells when it was later split, joined or unwrapped again; steps 3 and 4 are now exclusive (entering the colour mode ends bending); G and R on a handle are Kanzashi's own, so the view can be orbited with the middle button meanwhile; R turns a handle, which changes the direction of the wire there, and the turn is kept after bending ends.

## 0.4.0（試作）

- エージェント向けのスキル `skills/kanzashi/SKILL.md`（英語は `SKILL.en.md`）と入口 `AGENTS.md`。髪の調整の流れと、ユーザーに確認する所を決めた。
- `scripts/kanzashi_run.py`：検出済みの髪は毛束を残して UV だけを作り直す。`--swap`（張り替え）、`--apply`（形の確定）、`--redetect`（検出のやり直し）を足した。UV の検査に落ちたときは終了コードが 1 になる。
- `scripts/kanzashi_preview.py`：毛束ごとの色の画像（前・後ろ・左・右と UV）を出す。
- `tools/install_addon.py`：アドオンが入っているかを調べる（`--check`）、ZIP を作って拡張機能として入れる。
- `skills/kanzashi/scripts/hair_penetration.py`：エージェントの確認用。毛束ごとに、体へ入っている深さ・面積・毛先か途中かを調べる（`check`）。ワイヤーを外へ動かして直す（`fix`、新しいファイルに保存）。アドオンには入れていない。スキルに、直し方をユーザーに聞く工程を足した。

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
