# Kanzashi：エージェント向けの入口 / entry for agents

このリポジトリは、Blender のアドオン Kanzashi（生成した髪を毛束に分ける・塗って直す・ワイヤーで曲げる・毛束ごとの UV）と、それをエージェントが使うためのスキルです。

- **髪の調整を頼まれたとき、または生成した髪を整える段に来たとき**：[skills/kanzashi/SKILL.md](skills/kanzashi/SKILL.md) を読み、その流れと「ユーザーに確認する所（★）」に従います。English: [skills/kanzashi/SKILL.en.md](skills/kanzashi/SKILL.en.md).
- アドオンは `kanzashi/` に入っています。入っているかを調べるのは `python tools/install_addon.py --check`、入れるのは `python tools/install_addon.py` です。**入れる前にユーザーの許可を取ります。**
- 元のモデルのファイルを書き換えません。スクリプトは結果を新しいファイルに出します。

## このリポジトリを直すとき

- 動きを変えない直しの後は、手元の髪のファイルで `tests/regress.py` の結果を前後で比べます（[README.md](README.md) の「テスト」）。
- パネルの文字を足したら、`kanzashi/i18n.py` に英語を足し、`python tools/check_i18n.py` を通します。
- `ruff check .` と `ruff format .` を通します。
- 版を上げるときは、`VERSION`・`kanzashi/__init__.py`・`kanzashi/blender_manifest.toml` をそろえます（`tools/build_packages.py` が食い違いを止めます）。
- メッシュの属性（`lw_*`）、シーンの設定（`lida_hs_*`）、モディファイアやノードグループの名前は変えません。変えると、前の版で作ったファイルの続きができなくなります。
- モデル・テクスチャをリポジトリに入れません。
