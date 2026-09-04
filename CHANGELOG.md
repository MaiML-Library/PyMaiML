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
- 依存関係の疎通確認用スモークテスト(`tests/test_smoke.py`)。
- `pymaiml.serialization`: `maiml_domain`のオブジェクトツリーを実際の
  `.maiml` XMLへ書き出す`dumps()`/`dump()`を実装。MaiML-Domainの検証用
  スクリプト(`tests/build_sample_maiml.py`)にあった変換ロジックを、
  document/protocol(method・program階層のtemplateも含む)/data
  (material/condition/result)/eventLog(extension/global/classifier含む)
  /pnmlの全構造要素、およびproperty/content約70種類全てに一般化した。
  `loads()`/`load()`(読み込み方向)は未実装(`NotImplementedError`)。
- `pymaiml.validation`: 公式MaiML-Schema-1_0(`pymaiml/schema/`に同梱)
  によるXSD検証と、MaiML AI Common Specificationの補足ルール
  (EVT-02のlifecycle complete判定、ref参照先の型チェック、XES名前空間
  の厳密一致、秘匿禁止要素など)を`validate(path) -> ValidationResult`
  として提供。maiml-schema-validator Claude skillの検証スクリプトと
  同等のチェックをライブラリAPI化したもの。
- `pymaiml.builders`: `IdFactory`(id/uuid採番)、
  `infer_property()`/`infer_content()`(Pythonの値の型からproperty/content
  クラスを推定)、`new_complete_event()`(EVT-02対応の
  `lifecycle:transition="complete"`イベント組み立て)を追加。
- 依存関係に`lxml`を追加(`pymaiml.validation`が使用)。
- 上記3モジュールに対するテスト(`tests/test_serialization.py`・
  `tests/test_validation.py`・`tests/test_builders.py`)を追加。生成した
  `.maiml`が実際にスキーマ検証を通ることまで確認している。

## [0.1.0] - 未リリース

- 初期スキャフォールドのバージョン。
