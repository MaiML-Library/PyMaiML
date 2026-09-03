# Changelog

このプロジェクトの変更点はこのファイルに記録します。
形式は [Keep a Changelog](https://keepachangelog.com/) に、バージョニングは
[Semantic Versioning](https://semver.org/) に準拠します。

MaiML-Library organization の方針により、MaiML仕様(業務ルール・シリアライズ
形式など)に影響する変更は、必ずGitHub Issue/PRでの議論を経てから、このファ
イルへの記載とあわせて行ってください。

## [Unreleased]

### Added
- リポジトリの雛形を作成。`maiml_domain`(MaiML-Domain, v0.1.0タグ)への
  pip依存を`pyproject.toml`に定義。
- パッケージ`pymaiml`の初期構成(`__init__.py`のみ、実装はこれから)。
- 依存関係の疎通確認用スモークテスト(`tests/test_smoke.py`)。

## [0.1.0] - 未リリース

- 初期スキャフォールドのバージョン。
