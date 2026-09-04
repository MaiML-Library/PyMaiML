# Changelog

このプロジェクトの変更点はこのファイルに記録します。
形式は [Keep a Changelog](https://keepachangelog.com/) に、バージョニングは
[Semantic Versioning](https://semver.org/) に準拠します。

MaiML-Library organization の方針により、MaiML仕様(業務ルール・シリアライズ
形式など)に影響する変更は、必ずGitHub Issue/PRでの議論を経てから、このファ
イルへの記載とあわせて行ってください。

## バージョニングポリシー

このリポジトリは `x.y.z` 形式の [Semantic Versioning](https://semver.org/)
に準拠しますが、現在はまだ正式リリース前(`0.y.z`)の段階です。SemVerの
慣習に従い、メジャーバージョン `x` が `0` の間は `x` を固定し、以下の基準で
バージョンを管理します(MaiML-Domainと共通の方針です)。

- **破壊的変更**(既存APIの必須引数の追加・変更、公開インターフェースの
  変更など): `y`(マイナー)を上げる。あわせて **GitHub の Release 機能**
  でリリースノートを作成する。Releaseを作成するとリポジトリをWatchしている
  メンバーに通知が届くため、破壊的変更を能動的に知らせる目的も兼ねる。
- **後方互換を保った変更**(機能追加・バグ修正など): `z`(パッチ)を上げる。
  この場合は軽量な `git tag` のみでよく、GitHub Releaseの作成は不要。

`1.0.0` へ上げるタイミング(=正式リリース)は、APIが安定し外部からの利用に
耐えると判断した時点とします。`1.0.0` 以降は標準的なSemVerに従い、
破壊的変更は `x`(メジャー)、機能追加は `y`(マイナー)、バグ修正は
`z`(パッチ)を上げます。

なお、依存先である `maiml-domain` のバージョンを上げる(`pyproject.toml`の
`@vX.Y.Z`指定を更新する)こと自体も、このSDKにとっての変更として扱い、
その内容(Domain側で何が変わったか)に応じて上記の基準でバージョンを
判断してください。

## [Unreleased]

### Added
- リポジトリの雛形を作成。`maiml_domain`(MaiML-Domain, v0.1.0タグ)への
  pip依存を`pyproject.toml`に定義。
- パッケージ`pymaiml`の初期構成(`__init__.py`のみ、実装はこれから)。
- 依存関係の疎通確認用スモークテスト(`tests/test_smoke.py`)。

## [0.1.0] - 未リリース

- 初期スキャフォールドのバージョン。
