# Kanzashi：エージェント向けの入口 / entry for agents

このリポジトリは、Blender のアドオン Kanzashi（生成した髪を毛束に分ける・塗って直す・ワイヤーで曲げる・毛束ごとの UV）と、それをエージェントが使うためのスキルです。

- **髪の調整を頼まれたとき、または生成した髪を整える段に来たとき**：[skills/kanzashi/SKILL.md](skills/kanzashi/SKILL.md) を読み、その流れと「ユーザーに確認する所（★）」に従います。English: [skills/kanzashi/SKILL.en.md](skills/kanzashi/SKILL.en.md).
- アドオンは `kanzashi/` に入っています。入っているかを調べるのは `python tools/install_addon.py --check`、入れるのは `python tools/install_addon.py` です。**入れる前にユーザーの許可を取ります。**
- 元のモデルのファイルを書き換えません。スクリプトは結果を新しいファイルに出します。

## このリポジトリを直すとき

- 動きを変えない直しの後は、手元の髪のファイルで `tests/regress.py` の結果を前後で比べます（下の「テスト」）。
- パネルの文字を足したら、`kanzashi/i18n.py` に英語を足し、`python tools/check_i18n.py` を通します。
- `ruff check .` と `ruff format .` を通します。
- 版を上げるときは、`VERSION`・`kanzashi/__init__.py`・`kanzashi/blender_manifest.toml` をそろえます（`tools/build_packages.py` が食い違いを止めます）。
- メッシュの属性（`lw_*`）、シーンの設定（`lida_hs_*`）、モディファイアやノードグループの名前は変えません。変えると、前の版で作ったファイルの続きができなくなります。
- モデル・テクスチャをリポジトリに入れません。

## テスト

コードを直したら、直す前と同じ結果になるかを、手元の髪のファイルで比べます（モデルはリポジトリに入れていません）。開いたファイルは保存しません。

```bash
blender -b hair.blend --python tests/regress.py -- --out before.json
```

```bash
python tests/compare.py before.json after.json
```

登録、検出、塗り直し、曲げ、UV、検査、張り替えと戻し、書き出し、確定の 9 段の結果を、数とハッシュで記録します。

## コードの配置

```
kanzashi/
  panel.py           パネルと登録
  ops_hair.py        ① 髪の登録、② 検出
  ops_paint.py       ③ 色の塗り直し
  ops_bend.py        ④ 曲げる、⑥ 終わる・確定
  ops_uv.py          ⑤ 毛束ごとの UV・検査・張り替え・書き出し
  common.py          上の 5 つが共に使う処理（表示の切り替え、面を拾う・塗る、つまみ）
  i18n.py            日本語と英語の文
  tree.py            毛束の検出
  edit.py            検出の後の編集（塗り直しの反映、毛束を隠す、形の確定）
  strand_uv.py       毛束ごとの UV と検査
  guard.py           UV を作った髪の印と、その検査
  swap.py            張り替えと書き出し
  strands.py rewire.py wire.py   検出とワイヤーの下の層
  blender_manifest.toml          拡張機能としての定義
tools/               build_packages.py（ZIP）、install_addon.py、check_i18n.py、make_figures.py（README の模式図 docs/fig_*.svg）
tests/               regress.py、compare.py
```
