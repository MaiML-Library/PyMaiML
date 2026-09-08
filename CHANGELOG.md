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
- `pymaiml.serialization`: 読み込み方向`loads()`/`load()`を実装。
  `LoadedMaiml`(`root`/`namespaces`/`ids`)を返す。「既存のprotocolのみの
  MaiMLファイルを読み込み、`document`/`protocol`をそのまま引き継いで
  新たな`data`/`eventLog`を組み立てる」というユースケースに対応するため、
  `namespaces`(ルート要素が宣言していた名前空間の再現用)と
  `ids`(`IdFactory.from_existing_ids()`と組み合わせた新規id採番時の
  衝突回避用)をあわせて提供する。`dumps()`の出力を`loads()`で読み戻し、
  再度`dumps()`した結果が元の出力とバイト単位で一致することを確認済み。
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
- `pymaiml.builders.IdFactory`: `reserve()`/`from_existing_ids()`を追加。
  `pymaiml.serialization.load()`で読み込んだ既存ファイルのid一覧を
  そのまま渡すことで、新規に採番するidが既存ファイルのidと衝突しないこと
  を保証できる。
- `pymaiml.builders.infer_property()`/`infer_content()`に`xsi_type=`
  (`maiml_domain`のクラス、またはxsi:type名の文字列)を追加。`protocol`
  要素の汎用データコンテナ(材料テンプレート等)はほとんどの場合、値が
  まだ無いプレースホルダーだが、xsi:typeはスキーマ上必須のため、値から
  推定できないこのケースに対応できるようにした。`xsi_type=`・
  `value=`/`values=`のいずれも与えなかった場合は(推定不能として)
  ValueErrorを送出する。`PropertyListType`のように`value`/`values`
  パラメータ自体を持たないクラスも、コンストラクタの実シグネチャを見て
  正しく組み立てられる。
- `pymaiml.builders.XsiTypeRegistry`を追加。`infer_property()`/
  `infer_content()`に`registry=`として共有インスタンスを渡すことで、
  `protocol`側のプレースホルダーと対応する`data`側の実測値記録とで、
  同じ`key`が常に同じxsi:typeになることを保証する(実測値のPython型
  から推定した場合と食い違う可能性がある場合でも、登録済みの型を優先
  する)。同じkeyに異なるxsi:typeを再登録しようとした場合、または
  property/contentの種類を跨いで同じkeyを使おうとした場合はエラーに
  なる。
- 依存関係に`lxml`を追加(`pymaiml.validation`と`pymaiml.serialization`の
  読み込み側が使用)。
- 上記3モジュールに対するテスト(`tests/test_serialization.py`・
  `tests/test_validation.py`・`tests/test_builders.py`)を追加。生成した
  `.maiml`が実際にスキーマ検証を通ることに加え、「既存protocolファイルを
  読み込んで新規data/eventLogを追加し、スキーマ検証まで通す」ユースケース、
  および「protocol側の値なしプレースホルダーと対応するdata側の実測値が
  同じxsi:typeになる」ことをend-to-endで検証するテストを含む。
- `pymaiml.serialization.dumps()`に`drop_stale_signature=`引数を追加。
  `document.signature`は`loads()`/`dumps()`がただの1フィールドとして機械的
  に往復させるだけの生XML文字列であり、`data`/`protocol`など他の部分が
  編集されたかどうかは一切関知しない。そのため「ロード→編集→出力」の
  ワークフローで、編集後に`document.signature`を明示的にクリアし忘れると、
  内容的にはもう無効なはずの古い署名がそのまま出力に残ってしまう
  (署名生成・暗号学的検証そのものはCONTRIBUTING.mdの方針どおりpymaiml外
  (MaiML-TOOLS層)の責務だが、「編集されたかどうか」はSDK内で`loads()`→
  ミューテーションが完結するpymaimlでしか検知できない)。
  `loads()`が返す`LoadedMaiml`はロード直後の`root`の`copy.deepcopy()`を
  非公開の`_snapshot`として保持するようになり、
  `dumps(root, drop_stale_signature=loaded)`は現在の`root`と
  `loaded._snapshot`を(`document.signature`を除いて)比較し、署名以外の
  内容が変わっていれば出力から`<Signature>`要素を省く
  (`root.document.signature`自体は書き換えない)。`maiml_domain`の
  `DocumentType`/`MaimlRootType`等は`dataclass`ではなく独自`__init__`の
  クラスで`__eq__`も未定義のため、比較は`_build_maiml_element()`
  (`dumps()`本体から切り出した木構築処理を`_write_document(...,
  suppress_signature=True)`付きで両者に適用)によるXMLフィンガープリント
  比較で行う。`drop_stale_signature=None`(デフォルト)では従来どおり
  署名は無条件に素通しされ、後方互換。`loads()`を経由しない(スナップ
  ショットを持たない)`LoadedMaiml`を渡した場合は分かりやすい`ValueError`
  を送出する。回帰防止テストを4件追加
  (`test_drop_stale_signature_keeps_signature_when_nothing_changed`、
  `test_drop_stale_signature_drops_signature_when_content_edited`、
  `test_drop_stale_signature_without_edits_matches_plain_dumps`、
  `test_drop_stale_signature_requires_a_snapshot_from_loads`)。

### Fixed
- `pymaiml/__init__.py`: モジュールdocstringに`loads/load is not
  implemented yet`という古い記述が残っており(両関数とも実装済み)、
  `help(pymaiml)`で最初に読まれる箇所で実装状況を誤解させていた不具合を
  修正(外部レビュー所見08)。
- `pymaiml.serialization`: `<uncertainty>`要素が書き込み・読み込みの両方で
  無視されていた不具合を修正。スキーマの`uncertaintyBaseType`は
  `propertyBaseType`/`contentBaseType`共通の抽象基底型であり、
  `maiml_domain`側の`uncertainties`パラメータは元々全てのproperty/content
  クラスにモデル化されていた(`pymaiml`側の実装漏れであり、
  `maiml_domain`の制限ではなかった)。`_write_property_or_content()`/
  `_read_property_or_content()`に`tag=`引数を追加し、同じ具象クラスを
  `<uncertainty>`タグとしても書き出し/読み込みできるようにした。
- `pymaiml.serialization`: `_parse_scalar_text()`/`_format_value()`の
  xsi:type判定が大文字小文字を区別する部分文字列一致
  (例:`"Float" in xsi_type`)だったため、`pymaiml._xsi_registry`が
  クラス名の先頭一文字だけを小文字化して生成するxsi:type名
  (`FloatType` → `floatType`)に対しては判定が常に一致せず、bareな
  scalar/list型(float/double/decimal/int/long/short/byte/boolean/
  dateTime/uuid/hexBinary/base64Binary)の実測値が`loads()`後もPython型
  へ変換されず文字列のまま返っていた不具合を修正。判定を
  `xsi_type.lower()`同士の比較に変更し、大文字小文字の位置に依存しない
  ようにした(`Content*`/`unsigned*`接頭辞を持つ型はクラス名中の位置が
  ずれていたため偶然影響を受けていなかった)。
- 上記2件の回帰防止テストを`tests/test_serialization.py`に追加
  (`test_uncertainty_round_trips_through_dumps_and_loads`、
  `test_bare_scalar_types_round_trip_with_correct_python_type`)。
  ユーザー提供の実データファイル6件(ESEMstandard.1/.2、FSEMgold.2、
  DAFMgoldcorrected.1/.2、CCORRELATION)を`pymaiml.builders`/
  `pymaiml.serialization`のみで再構築するテストを通じて発見した
  不具合(特に後者はCCORRELATION.maimlの`<uncertainty>`付き
  measurement値で顕在化した)。
- `pymaiml.serialization`: `document`に`Signature`を持つファイルを
  `loads()`→`dumps(..., extra_namespaces=loaded.namespaces)`という、
  `LoadedMaiml.namespaces`のdocstringが案内する手順どおりに再書き出しする
  と、ルート`<maiml>`要素に同じ`xmlns:nsN`宣言が二重に現れ
  `xml.parsers.expat.ExpatError: duplicate attribute`で失敗していた
  不具合を修正。`<Signature>`/`<EncryptedData>`は`ET.fromstring()`で
  読み直してそのまま木に追加する生XMLであり、そこで実際に使われている
  名前空間を`xml.etree.ElementTree`が木全体走査で発見してルート要素に
  自動で`xmlns:nsN`宣言を追加する一方、こちらが`extra_namespaces`から
  設定した同名のリテラル属性の存在をElementTreeは関知しないため、両者が
  同じプレフィックスを使うと二重宣言になっていた。`dumps()`に
  `_dedupe_root_namespace_decls()`を追加し、ルート要素上で同名・同値の
  宣言が重複したときは1つにまとめ、同名で値が異なる(真の競合)場合は
  分かりやすい`ValueError`を送出するようにした。
- `pymaiml.serialization`: `<description>`/`<format>`のような
  `xs:string minOccurs="0"`の要素が、存在するが空(`<description/>`)の
  場合と要素そのものが存在しない場合を区別できず、どちらも`None`として
  読み込まれ、往復後に要素が消えていた不具合を修正
  (`value`側は空文字列として正しく保たれており、ライブラリ内で挙動が
  不統一だった)。`_text_of()`と、独自に同じ判定を行っていた
  `_read_property_or_content()`/`_read_insertion()`のそれぞれで、
  「子要素が存在しない」場合のみ`None`を返し、存在する場合は
  `.text or ""`で空文字列を返すよう統一した。
- README.md: 「ローカルでMaiML-Domainと同時に開発する場合」の手順を
  記載どおりに実行すると、`pip install -e ../MaiML-Domain`で入れた
  editable版が、続く`pip install -e ".[dev]"`によってエラーなく
  アンインストールされ、`git+...@v0.1.0`タグ由来の固定版に静かに
  差し替わってしまう(Domain側を編集しても反映されない状態に気づけない)
  不具合を修正。`dependencies`のdirect URL指定(`maiml-domain @
  git+...`)がある限り`pip install -e ".[dev]"`は毎回このタグ版を
  再インストールするため、`pip install --no-deps -e .`を使い、
  `[dev]`の依存(`lxml`/`pytest`)は個別にインストールする手順に修正した。
- 上記のうち`pymaiml.serialization`側2件について、回帰防止テストを
  `tests/test_serialization.py`に追加
  (`test_signature_round_trips_without_duplicate_namespace_error`、
  `test_dumps_rejects_genuinely_conflicting_root_namespace_declaration`、
  `test_empty_property_value_and_description_round_trip_as_empty_string`、
  `test_absent_property_description_still_round_trips_as_none`、
  `test_empty_insertion_format_round_trips_as_empty_string`、
  `test_absent_insertion_format_still_round_trips_as_none`)。
  いずれも外部レビュー(2026-09-07、PyMaiML `690edd6`/MaiML-Domain
  `be11e5c`時点)で報告された「要修正」所見3件の再現コードに基づく。
- `pymaiml.serialization`: `units`/`formatString`/`scaleFactor`属性を
  持つ`<property>`/`<content>`を`loads()`する際、書き込み側は
  `hasattr(obj, "units")`等で対応クラスかどうかを確認しているのに対し、
  読み込み側は無条件に`kwargs`へ積んでいたため、対応しないxsi:type
  (例:`stringType`に`units`)だと生の`TypeError`(`__init__() got an
  unexpected keyword argument 'units'`)がそのまま呼び出し側に漏れて
  いた不具合を修正。`_read_property_or_content()`で
  `inspect.signature(cls.__init__).parameters`を使って対象クラスが
  そのパラメータを受け付けるか事前に確認し、受け付けない場合は
  `pymaiml.validation.validate()`の利用を促す分かりやすい`ValueError`
  を送出するようにした。回帰防止テストを2件追加
  (`test_units_on_a_class_that_does_not_accept_it_raises_a_clear_error`、
  `test_units_formatstring_scalefactor_on_a_class_that_accepts_them_still_work`)。

### Changed
- README.md: `pymaiml.serialization`の節に既知の制限を2点追記。
  (1) `loads()`はスキーマ妥当な入力のみを対象としており、基数
  (`minOccurs`)違反のファイルは`maiml_domain`側の`ValueError`で読み込みが
  止まるため、診断・修復用途には`pymaiml.validation.validate()`を先に
  使うべきこと。(2) `document`に`Signature`を持つファイルを`loads()`→
  `dumps()`で往復させると`dumps()`のpretty-print整形により署名対象の
  バイト列が変わり、他の準拠実装が付与した署名は無効化されること
  (`pymaiml`自身が書いた署名を読み直す場合はC14N出力が一致するため
  影響を受けない)。
- README.md: `pymaiml.validation`の節に、同梱XSD(`pymaiml/schema/
  MaiML-Schema-1_0/`)のうち5本(`maiml.xsd`/`maiml-core.xsd`/
  `maiml-document.xsd`/`maiml-property.xsd`/`xenc-schema.xsd`)が公式
  配布版に無い`xs:import`(`xmldsig`/`xmlenc`名前空間)を追記した改変版
  であることを明記。公式配布版はこれらのimportを欠いておりlxmlで
  スキーマオブジェクトを構築できないための実務的な補完であることと、
  `maiml-schema-validator`スキルの`reference/`側にも同じ差分を適用した
  コピーを保持していることを併記。
  以上4件は外部レビュー(2026-09-07、PyMaiML `690edd6`/MaiML-Domain
  `be11e5c`時点)の「要検討」所見のうち、コード修正が妥当と判断した
  1件(units/formatString/scaleFactor)と、設計上の割り切りとして
  ドキュメント化に留めるのが妥当と判断した3件(署名の再整形、
  loads()の対象範囲、同梱XSDの差分)への対応。

## [0.1.0] - 未リリース

- 初期スキャフォールドのバージョン。
