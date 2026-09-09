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
- `tests/test_xsd_completeness.py`を追加。MaiML-Schema-1_0(`pymaiml/schema/`
  同梱版)を正として、(1)全`<xs:complexType>`が同名(先頭大文字化)の
  `maiml_domain`クラスを持つか、(2)`maiml-property.xsd`の全property/
  content xsi:type(`propertyBaseType`/`contentBaseType`を直接継承する
  complexType)が`pymaiml._xsi_registry`に登録されているか、をそれぞれ
  双方向(過不足なし)でチェックする。「XSDが更新されたのに、対応する
  クラスをMaiML-Domain側に追加し忘れる」ケースをCIで検出できるようにする
  ためのテスト。`maiml_domain`側のシンプル型(`Uuid`等)・xs:group由来の
  mixin(`GlobalObjectContent`/`EncryptionType`)・実装詳細
  (`_StrictAttributesMixin`)は、XSDのcomplexTypeに対応しないことが既知の
  例外として明示的に許容リスト化してある。現時点(MaiML-Domain `v0.2.0`)
  では過不足なし(5件すべて合格)。

### Fixed
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
- `pymaiml.builders.infer_property()`/`infer_content()`: `values=`の
  homogeneous判定が実際にはvalues[0]しか見ておらず、例えば
  `infer_property("ex:value", values=[1, 2, "abc"])`のような型の
  混在したリストでもエラーにならず`IntListType`が選ばれ、"abc"が
  そのまま紛れ込んでいた不具合を修正(docstringには元々
  "must be non-empty and homogeneous"と明記されていたが、実装がそれを
  満たしていなかった)。`_infer_homogeneous_list_class()`を追加し、
  values[0]から選んだクラスに、残りの全要素も`_match()`と同じ規則で
  一致するかを確認するようにした。「Pythonのclassが完全一致」ではなく
  「選択されたMaiML型に(同じ推定テーブル上で)変換可能か」で判定して
  いるため、`bytes`/`bytearray`混在(どちらも`Base64Binary*ListType`)は
  引き続き許可されるが、`bool`/`int`混在(`bool`は`int`のサブクラスだが
  別のMaiML型`BooleanListType`/`IntListType`に対応するため)は拒否される。
  回帰防止テストを`tests/test_builders.py`に5件追加
  (`test_infer_property_rejects_heterogeneous_values`、
  `test_infer_content_rejects_heterogeneous_values`、
  `test_infer_property_rejects_bool_mixed_with_int`、
  `test_infer_property_accepts_bytes_and_bytearray_together`、
  `test_infer_property_heterogeneous_error_names_the_offending_element`)。
  外部レビューで報告された所見。
- `pymaiml.builders.IdFactory.new_id()`: 生成されるidは常に`prefix + 連番の
  整数`であるにもかかわらず、`prefix`自体がxs:ID(NCName)として妥当かを
  一切確認していなかったため、`ids.new_id("123")`のように数字始まりの
  `prefix`を渡すと`"1231"`のようなxs:ID違反のidをそのまま生成できてしまう
  問題を修正。`_is_valid_ncname()`を追加し、`new_id()`が各`prefix`を
  (そのprefixで最初に呼ばれた時点で1回だけ)検証、数字始まり・`:`を含む・
  空文字列など、NCNameとして不正な`prefix`は分かりやすい`ValueError`で
  即座に拒否するようにした(`IdFactory`のdocstringにdoctest例を追記)。
  回帰防止テストを`tests/test_builders.py`に7件追加
  (`test_new_id_rejects_prefix_that_would_not_be_a_valid_xs_id`
  ×5パターン、
  `test_new_id_accepts_a_prefix_that_is_itself_a_valid_xs_id`×6パターン、
  `test_new_id_rejects_bad_prefix_even_after_a_good_prefix_was_already_used`、
  `test_new_id_only_validates_a_prefix_once_per_factory`)。
  外部レビューで報告された所見。

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
- `pyproject.toml`の`dependencies`(`maiml-domain @ git+...@v0.2.0`という
  direct reference)の上に、PyPI公開時にはこの形式のまま使えない旨と、
  公開後に書き換えるべき形(`maiml-domain>=0.2,<0.3`)をコメントで併記。
  PyPAの仕様上、public index serverはアップロードされたdistributionの
  依存関係にdirect referenceを含めることを許可すべきではないとされて
  おり、実際PyPIへのアップロードもこの形式のままでは拒否される。
  開発段階の現在はタグ固定のgit依存(`main`追従より安全)のままで問題
  ないため、`dependencies`自体は変更していない。`CONTRIBUTING.md`に
  「PyPI公開前の対応」節を新設し、(1) MaiML-Domainを先にPyPI公開、
  (2) `dependencies`をバージョン範囲指定へ書き換え、(3) `pymaiml`自体を
  PyPI公開、という順序を明文化した。外部レビューで報告された所見。

### Security
- 信頼できない(未検証の)MaiML XMLを解析するlxmlパーサーに
  `resolve_entities=False`と`no_network=True`を明示するハードニングを
  実施(新モジュール`pymaiml._xml_security.make_untrusted_input_parser()`)。
  従来`pymaiml.validation._xsd_validate()`は`etree.XMLParser(remove_blank_
  text=False)`のみで、lxmlの既定値(`resolve_entities=True`、
  `no_network=False`)に依存していたため、DOCTYPEで宣言した外部
  エンティティ(例: `<!ENTITY xxe SYSTEM "file:///etc/passwd">`)や
  ネットワーク越しの外部リソース参照が解決されうる状態だった(いわゆる
  XXE/entity-expansion脆弱性)。現状`validate()`はローカルファイルしか
  扱わないためすぐに悪用可能というわけではないが、`pymaiml.validation`
  が将来APIやアップロードファイルなど未検証の入力を扱う可能性を見込み、
  「このライブラリは外部エンティティ・ネットワークリソースを一切解決
  しない」という方針をコードで明示的に固定した。同様に未検証入力を
  読む`pymaiml.serialization.loads()`(`_lxml_etree.fromstring(data)`、
  従来パーサー未指定=lxml既定値)も同じ`make_untrusted_input_parser()`を
  使うよう変更。
- 一方、同梱の信頼済みXSDスキーマ本体を読み込む
  `pymaiml.validation._load_schema()`(`etree.parse(str(maiml_xsd))`)は
  意図的に上記のハードニング済みパーサーを共有せず、従来どおりの
  パーサーのまま維持した。こちらはスキーマファイル間の`xs:import`/
  `xs:include`(ローカルファイルパスによる相互参照)を解決する必要が
  あり、未検証のMaiML入力とは信頼レベルが異なるため。両者を意図的に
  別々の、名前の付いたコード経路として分離しておくことで、一方への
  変更がもう一方へ静かに波及することを防ぐ設計とした。
- 上記の変更に伴い、`pymaiml.validation._xsd_validate()`で
  `schema.validate(doc)`が`lxml.etree.XMLSchemaValidateError`
  (internal error)を送出するケースを新たに捕捉するよう修正。
  `resolve_entities=False`により未解決のまま残ったDOCTYPE由来の
  エンティティ参照ノードを含む木は、libxml2のスキーマバリデータが
  正常に走査できず内部エラー例外を送出することがある(実際に
  回帰テストで発生を確認)。これを捕捉せずに伝播させると
  `validate()`が例外で落ちてしまうため、通常のXSD違反と同様に
  `Finding(code="XSD-02")`として報告するよう変更した。
- 回帰テスト`tests/test_xml_security.py`を追加。ハードニング済み
  パーサーが外部ファイルエンティティを展開しないこと・ネットワーク
  リソースへアクセスしようとしないことを直接確認するテスト、
  `validate()`/`loads()`がそのような入力に対して例外を送出したり
  秘匿情報をエラーメッセージ経由で漏らしたりしないことを確認する
  テスト、通常の正当なMaiMLファイルの読み込み・検証がハードニング後も
  引き続き成功することを確認するテスト、`_load_schema()`が引き続き
  ローカルXSD間の`xs:import`/`xs:include`を解決できることを確認する
  テストを含む。ユーザー提案。
- `pymaiml._xsi_registry`: モジュールレベルの`XSI_TYPE_TO_CLASS`/
  `CLASS_TO_XSI_TYPE`初期化が、`_build_registries()`(`maiml_domain.
  property.__all__`のリフレクション)を2回呼び出していた(それぞれ
  `.update(_build_registries()[0])`/`[1]`という書き方だったため)重複を
  解消。`XSI_TYPE_TO_CLASS, CLASS_TO_XSI_TYPE = _build_registries()`と
  1回の呼び出しで両方を受け取る形に変更。結果は元々同じ辞書の内容に
  なるため動作上のバグではなく、インポート時に無駄なリフレクション処理を
  もう一度実行していた分のコードの明快さの改善。ユーザー指摘。

### Changed(破壊的変更)
- **`pymaiml.serialization.dumps()`/`dump()`は、既存の`document.signature`
  (`<Signature>`)を常に出力から除外するよう変更しました。**
  `drop_stale_signature=`引数(署名以外の内容が変わっていなければ署名を
  維持する、変わっていれば省く)は廃止し、除外に条件分岐はなくなりました。
  これは本ファイル冒頭の`### Added`に記載した、`drop_stale_signature=`
  引数の追加エントリを置き換える変更です。
  理由は「署名以外が変わっていなければ安全に維持できる」という前提
  そのものがpymaimlの立場からは保証できないと判断したためです。MaiMLの
  `<Signature>`はJIS X 5093 / ETSI TS 101 903(XAdES)準拠のenveloped
  署名であり、Digestは署名時点の厳密なバイト列に対して計算されます。
  `dumps()`は`maiml_domain`のオブジェクトツリーからXMLを再構築する際、
  インデント・namespace宣言位置・属性順序・空要素表現などを含めて
  出力を作り直すため、内容(`document.signature`以外のフィールド)が
  一切変わっていなくても、署名時点の厳密なバイト列を再現できるとは
  保証できません。`pymaiml`は署名の生成・検証そのものを実装しておらず
  (`CONTRIBUTING.md`の「XML Signature(電子署名)の扱い」節を新設し、
  明文化しました)、この「バイト列が変わっていないかどうか」を判断する
  資格自体がpymaimlにはない、という整理です。
  影響: `pymaiml.serialization.loads()`は`<Signature>`を読み込み、
  `DocumentType.signature`に文字列として保持する動作(検証等への
  受け渡し用)は変更していません。変わるのは書き出し側のみで、
  「署名済みファイルをloads()→(無編集で)dumps()しても、出力に
  `<Signature>`は含まれない」という点が、以前(署名以外に変更が無ければ
  維持されていた)から変わります。署名済みファイルが必要な場合は、
  `dumps()`/`dump()`で内容を確定させた後に、その出力バイト列へ
  `maiml-signer`スキル等で改めて署名してください。`pymaiml`へ将来
  署名対応を追加する場合も、`pymaiml.serialization`とは独立した
  モジュール(例: `pymaiml.signature`)に分離することを`CONTRIBUTING.md`
  で推奨事項として明記しました。
  内部実装としては、`_write_document()`から`suppress_signature`引数と
  シグネチャ書き込み分岐そのものを削除、`_build_maiml_element()`からも
  同引数を削除、`_content_changed_since_snapshot()`(スナップショットとの
  差分検出)を削除、`LoadedMaiml._snapshot`(ロード時`copy.deepcopy()`)
  を削除しました。回帰テストは`tests/test_serialization.py`の
  drop_stale_signature系4件を、常時除外の挙動を確認する4件
  (`test_dumps_never_writes_a_document_signature`、
  `test_loads_still_reads_a_signature_dumps_never_wrote`、
  `test_dumps_drops_a_loaded_signature_even_with_no_further_edits`、
  `test_dumps_no_longer_accepts_drop_stale_signature`)に置き換えました。
  また、既存の`test_signature_round_trips_without_duplicate_namespace_
  error`(`<Signature>`往復時の名前空間重複バグの回帰テスト)は、
  `dumps()`がもう`<Signature>`を書き戻さないため前提が崩れたので、
  同じ`_dedupe_root_namespace_decls()`の保護を`<EncryptedData>`
  (`_write_encryption()`が同様に埋め込みXML断片をそのまま追記する経路)
  で検証する`test_encrypted_data_round_trips_without_duplicate_
  namespace_error`に置き換えました。ユーザー指摘・提案。

### Added
- README.md(`pymaiml.serialization`節)と`pymaiml/serialization.py`の
  モジュールdocstring(Known limitations)に、XMLコメント
  (`<!-- ... -->`)・処理命令(`<?...?>`)がload/dumpの往復で保持されない
  ことを明記。現在の`loads()`は対象のXSD要素だけを明示的に拾って
  `maiml_domain`オブジェクトへ変換する設計で、コメント・処理命令は
  そもそもモデル化していないため、`loads()`→`dumps()`で往復させると
  元のファイルにあったコメント・処理命令は失われる(XMLとして完全に
  losslessなround-tripは保証しない)。これは単なる開発者向けメモの
  消失には留まらない。コメントが「データの一部を意図的に省略している」
  といった、それ自体が意味を持つ情報を担っている場合、その情報ごと
  失われる点を明示的に注意喚起する。ユーザー指摘。
- **`pymaiml.query`モジュールを新設。** `serialization`/`validation`/
  `builders`とは独立した、読み取り専用の「ファイル内の一覧を取得する」
  ユーティリティ群として、以下4関数を提供します。
  - `get_uuids(xml_text)` -- `<uuid>`要素のテキストを一覧取得
    (出現箇所の種類を問わない: オブジェクトの識別uuid、`insertion`
    自身のuuid、`chain`/`parent`のuuidをすべて含む)。**重複除去はしない**
    (下記参照)。
  - `get_keys(xml_text)` -- `key=`属性値を一覧取得
    (`<property>`/`<content>`/`<chain>`/`<parent>`のいずれも対象)
  - `get_namespaces(xml_text)` -- 宣言されているカスタム名前空間を
    `{接頭辞: URI}`の`dict`で取得(デフォルト名前空間と`xsi:`は除外)
  - `get_insertion_uris(xml_text)` -- `<insertion>/<uri>`のテキストを
    一覧取得(外部ファイル参照のURI)

  リスト系関数はいずれも出現順を保持しますが、重複の扱いは`get_uuids()`
  だけ異なります。`get_keys()`/`get_insertion_uris()`は出現順を保持しつつ
  重複を除去します(`dict.fromkeys()`による先頭優先の重複除去)。
  `get_namespaces()`は`dict`を返すため、キーの挿入順がそのまま出現順に
  なります。一方`get_uuids()`は重複を除去せず、出現した`<uuid>`要素の
  テキストを全件そのまま返します(ユーザー指摘により変更)。`uuid`は本来
  オブジェクトを一意に識別するためのものであり、同じ値が複数回出現する
  こと自体が検出したい事実になり得るためです。重複除去した一覧が必要な
  場合は呼び出し側で`set(...)`や`list(dict.fromkeys(...))`を使うことを
  想定しています。

  設計上の要点は次のとおりです。
  - `pymaiml.serialization.loads()`を経由しません。`loads()`はスキーマ
    妥当な入力のみを対象とし、`maiml_domain`オブジェクトツリーの構築を
    要求しますが、`pymaiml.query`は生のXMLを直接(`lxml.etree`の
    `.iter()`による汎用的なタグ名/属性名の走査で)読むため、まだ
    スキーマ検証していないファイルに対する軽量な下調べとしても使えます。
  - `get_namespaces()`は、`LoadedMaiml.namespaces`(ルート`<maiml>`要素
    のみを見る)とは異なり、木全体を走査します。`pymaiml`自身の
    `dumps()`出力であれば`xml.etree.ElementTree`のシリアライザが
    使用中の名前空間をすべてルートへ引き上げるため`LoadedMaiml.
    namespaces`でも十分ですが、`pymaiml`の`dumps()`を経由していない
    外部生成ファイル(例: ルート以外の要素で`xmlns:ds`を宣言したまま
    署名されたファイル -- `dumps()`は署名を書き出さないため、
    署名付きファイルは必然的に外部由来です)では、名前空間がルート以外
    の要素に宣言されている可能性があり、`get_namespaces()`はそのケースも
    正しく検出します。同じ接頭辞に異なるURIが束縛されている場合は
    `ValueError`を送出します(`_dedupe_root_namespace_decls()`の
    「サイレントに片方を選ばず失敗する」という既存方針を踏襲)。
  - 4関数とも、`pymaiml.serialization.loads()`と同じ
    `pymaiml._xml_security.make_untrusted_input_parser()`(XXE/
    entity-expansion/networkハードニング済み)でXMLを解析します。
    「このファイルに何が入っているか一覧を取る」という用途は、
    未検証・未信頼な入力に対してまさに使われがちな操作であるため。

  `pymaiml/__init__.py`のモジュール概要とREADME.mdの「モジュール構成」に
  追記し、`tests/test_query.py`(13件、上記の重複除去・走査範囲・
  エラー送出・XXEハードニングをそれぞれ検証)を追加しました。
  ユーザー要望・設計指定。
- **`pymaiml.query`を、生のXMLを直接走査する独立実装から
  `maiml_domain`ベースの実装へ書き換え(破壊的変更)。** 上記のエントリで
  記述した「`serialization.loads()`を経由しない」という設計は撤回します。
  `get_uuids()`/`get_keys()`/`get_insertion_uris()`は、いまは
  `pymaiml.serialization.loads(xml_text)`を呼び出し、その結果の
  `maiml_domain`オブジェクトツリー(`loaded.root`)から値を読み取ります。
  理由は、「このファイルに何が入っているか」というPython向けの見え方は、
  このプロジェクトのPython系ツールが共有する唯一の正しいドメインモデルで
  ある`maiml_domain`経由で提供すべきであり、同じタグ/属性名を偶然一致
  させているだけの独立したXML走査実装をもう1つ持つべきではない、という
  より強いルールに従うためです。

  この変更の直接的な結果として、以下の3点があります。
  - `xml_text`はスキーマ妥当なMaiMLでなければなりません。
    `maiml_domain`のコンストラクタが要求するカーディナリティを満たさない
    入力に対しては、`loads()`と同じ例外(多くは`ValueError`、整形式でない
    XMLの場合はlxmlのパースエラー)がそのまま送出されます。以前この
    3関数がサポートしていた「スキーマ検証前のファイルに対する軽量な
    下調べ」という用途は、もう使えません(先に`validate()`または
    `load()`してください)。
  - この3関数のXXE/entity-expansion/networkハードニングは、内部で
    呼び出す`serialization.loads()`のものがそのまま適用されます。この
    3関数自体はもうXMLを直接パースしないため、独自に守るべきハードニング
    経路自体が存在しません。
  - URIを持たない`<insertion>`という不正な形は、もう`get_insertion_uris()`
    に到達し得ません。`InsertionType.__post_init__`が空/欠落した`uri`を
    拒否するため、そのような`insertion`はそもそも`maiml_domain`オブジェクト
    として構築できないからです(以前の実装が持っていた、URIなしの
    `insertion`をスキップする防御的な分岐は不要になり、削除しました)。

  `get_namespaces()`だけは例外として、今も生XMLを`lxml.etree`で直接
  解析します。名前空間宣言はXMLレベルの概念であり、`maiml_domain`の
  どのクラスにも保持されていない(`serialization`の「既知の制限」参照:
  `dumps()`は`extra_namespaces=`から再構築するだけで、`maiml_domain`側は
  一切名前空間を持たない)ため、読み替えるべきオブジェクトツリー上の
  情報がそもそも存在しないためです。

  内部実装として、`_iter_domain_objects()`という汎用ヘルパーを追加
  しました。`maiml_domain`の約30の構造クラス・約50のproperty/content
  リーフクラスを個別に分岐せず、`vars(obj)`を各クラスの`__init__`が
  属性を代入した順序のまま再帰的に辿ることで、`uuid`/`key`属性を持つ
  オブジェクトや`InsertionType`インスタンスを汎用的に収集します。これに
  より`maiml_domain`が将来クラスを追加しても`pymaiml.query`側の追随が
  不要になります(循環参照に備えた`id()`ベースの訪問済みガード付き。
  ただし`maiml_domain`自身が循環するオブジェクトグラフを生成することは
  ありません)。

  `README.md`の`pymaiml.query`節、`pymaiml/__init__.py`のモジュール概要、
  `tests/test_query.py`(既存の生XMLスニペットを使うテストを、
  `minimal_root`フィクスチャを土台にした実オブジェクトツリー経由のテストへ
  全面的に置き換え。「URIなしのinsertion」テストは、その形自体が
  `maiml_domain`では構築不能になったため削除し、代わりに
  `InsertionType`が`uri`を必須とすることを検証するテストを追加)を
  更新しました。ユーザー要望(「MaiML-Domainを使用するというルールの
  もと、コードを修正して」)。

## [0.1.0] - 未リリース

- 初期スキャフォールドのバージョン。
