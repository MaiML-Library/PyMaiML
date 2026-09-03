# PyMaiML

MaiML(JIS K 0200 / Measurement Analysis Instrument Markup Language)を
Pythonから扱うためのSDKです。

## MaiML-Domainとの関係

このSDKは、MaiML-Schema-1_0のcomplexTypeに1:1対応する純粋なデータモデルで
ある [MaiML-Domain](https://github.com/MaiML-Library/MaiML-Domain)
(`maiml_domain`パッケージ)の上に構築されています。

- `maiml_domain`: XSDに対応するデータクラス群のみ。業務ルール検証や
  XMLシリアライズは持たない、依存ライブラリゼロの基盤パッケージ。
- `pymaiml`(このリポジトリ): `maiml_domain`をpipの通常の依存パッケージ
  として取り込み、その上に以下を実装する層。
  - `.maiml`ファイルとの相互変換(シリアライズ/デシリアライズ)
  - MaiML AI Common Specificationの業務ルール検証
    (`lifecycle:transition="complete"`の必須化、`ref`参照先の型チェック等)
  - オブジェクトツリーを組み立てやすくする高レベルAPI

`maiml_domain`自体をこのSDKやCLIツールと同じリポジトリに置かず、あえて
別リポジトリに分離しているのは、複数言語のSDKやAPI/ツール層(将来追加され
うるもの)が同じ「唯一の正しいドメインモデル」を共有し、モデル自体の変更が
1箇所の議論(Issue/PR)で完結するようにするためです。

## インストール

```bash
pip install -e ".[dev]"
```

`pyproject.toml`の`dependencies`に`maiml-domain`がGit経由の依存として
指定されているため、`pip install`時に自動的に
`https://github.com/MaiML-Library/MaiML-Domain.git`の`v0.1.0`タグから
インストールされます。

```toml
dependencies = [
    "maiml-domain @ git+https://github.com/MaiML-Library/MaiML-Domain.git@v0.1.0",
]
```

### なぜ`main`ブランチではなく特定のタグを指定するのか

MaiML-Domainを`main`ブランチのまま参照すると、Domain側の将来の変更
(仕様追加・破壊的変更含む)がこちらに無断で流れ込んでしまいます。
バージョンタグ(`v0.1.0`など)に固定し、Domain側を更新したいときに明示的に
このバージョン指定を上げる、という運用にしてください。Domain側の
`CHANGELOG.md`と合わせて確認すると、何が変わったか追跡しやすくなります。

### ローカルでMaiML-Domainと同時に開発する場合

Domain側とSDK側を手元で同時に編集しながら動かしたい場合は、兄弟フォルダ
としてクローンした上でeditableインストールに切り替えると便利です。

```bash
pip install -e ../MaiML-Domain
pip install -e ".[dev]"
```

この場合`pyproject.toml`の変更は不要です(後からインストールした
editable版がpip環境内で優先されます)。ただし、CI/リリースビルドでは
必ず上記のGit+タグ指定の依存関係を使ってください。

## テスト

```bash
pytest
```

`tests/test_smoke.py`は、`maiml_domain`への依存が正しく解決されている
ことだけを確認する最小限のスモークテストです。SDK自体の機能(シリアライズ
・業務ルール検証など)はこれから実装していきます。

## ライセンス

Apache-2.0。詳細は[LICENSE](LICENSE)を参照してください。

## Contributing

MaiML仕様(業務ルール・シリアライズ形式など)に影響する変更は、必ず
GitHub Issue/PRでの議論を経てから行い、`CHANGELOG.md`に記載してください。
組織全体の方針は
[MaiML-Library/.github](https://github.com/MaiML-Library/.github/blob/main/profile/README.md)
を参照してください。
