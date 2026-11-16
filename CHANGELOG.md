# 変更履歴

## 0.2.0（試作）

- パネルを日本語と英語で使えるようにした。いちばん上の欄で Auto／日本語／English を選ぶ（Auto は Blender の表示言語に合わせる）。
- 英語の説明 `README.en.md`。
- 英語の文の抜けと `%` の書式の食い違いを調べる `tools/check_i18n.py`。

English: the panel now works in Japanese and English (Auto / 日本語 / English at the top of the panel), with an English README.

## 0.1.0（試作）

- 毛束の検出、色の塗り直しによる付け替え、ワイヤーでの曲げ、毛束ごとの UV（検査・テクスチャ用の書き出し・張り替え・元に戻す）。
- アドオン（パネル）と、パネルなしで動かすスクリプト `scripts/kanzashi_run.py`。
- 配布用の ZIP を作る `tools/build_packages.py`。
