# Contributing

MaiML仕様(業務ルール・シリアライズ形式など)に影響する変更は、必ず
GitHub Issue/PRでの議論を経てから行い、`CHANGELOG.md`に記載してください。
組織全体の方針は
[MaiML-Library/.github](https://github.com/MaiML-Library/.github/blob/main/profile/README.md)
を参照してください。

## MaiML-Schema-1_0が更新されたときの手順

pymaimlは、`property`/`content`(約70種類の値型)の層は
`maiml_domain.property.__all__`をリフレクションで読むことでXSDの変更に
かなり自動追従しますが、`document`/`protocol`/`data`/`eventLog`/`pnml`
などの構造部分(`pymaiml/serialization.py`の`_write_*`/`_read_*`)は、
`maiml_domain`の各クラスの**今のコンストラクタシグネチャ**をそのまま
決め打ちで呼んでいます。この結合を無理に汎用化するより、「XSD更新時に
差分を確実に検出できるチェックリストを用意しておく」方針を取っています。
XSDを更新する際は、以下を順に確認してください。

1. **XSD本体を3箇所に反映する。** MaiMLの公式XSDは1つのリポジトリに
   集約されていません。以下すべてを新版に置き換えてください(片方だけ
   更新すると「pymaiml側は新XSDで通るのにスキーマ検証だけ古いまま」と
   いった食い違いが起きます)。
   - `pymaiml/schema/MaiML-Schema-1_0/*.xsd`(`pymaiml.validation`が実際に
     検証で使う束)
   - `maiml-schema-validator`スキルの`reference/MaiML-Schema-1_0/`(同じ
     内容のコピーを独立に保持しています)
   - `MaiML-Domain`リポジトリ側のクラス定義そのもの(下記2)

2. **`MaiML-Domain`を新XSDへ追従させる。** `maiml_domain`は別リポジトリ
   なので、まずそちらで新しい/変更されたcomplexTypeに対応するクラスを
   追加・修正し、リリースタグを打ちます。`pyproject.toml`の
   `dependencies`にあるgit+タグ指定
   (`maiml-domain @ git+...@vX.Y.Z`)をこの新タグに上げてから、以降の
   手順に進んでください。

3. **`pymaiml._xsi_registry`の全型を検証するテストを実行する。**
   `_xsi_registry.XSI_TYPE_TO_CLASS`/`CLASS_TO_XSI_TYPE`は
   `maiml_domain.property.__all__`から自動生成されるため、新しい
   property/content型は基本的に無修正で使えるようになりますが、それは
   「クラス名の先頭一文字を小文字化したものがxsi:type名と一致する」と
   いう命名規則が守られている場合に限ります。新旧の型一覧を突き合わせ、
   各xsi:typeについて代表値を1つ用意して
   `_format_value()` → `_parse_scalar_text()` の往復でPython型が
   元に戻ることを確認するテストを実行してください(既存の
   `test_bare_scalar_types_round_trip_with_correct_python_type`と同じ
   パターンで、新しく増えた型ぶんパラメータを追加する形が最も簡単です)。

4. **`pymaiml.builders`のPython型マッピングとの差分を確認する。**
   `_xsi_registry`とは対照的に、`builders.py`の
   `_SCALAR_CLASS_BY_TYPE`/`_LIST_CLASS_BY_TYPE`(Pythonの値の型 →
   `maiml_domain`クラスの対応表)は自動生成ではなく手書きのテーブルです。
   XSDに新しいプリミティブ型が追加されて、それをPythonのどの組み込み型
   から推定すべきかが自明でない場合は、ここへの追記が必要です(単に
   xsi:type名の命名規則に従っただけの新型なら、`infer_property()`/
   `infer_content()`を`xsi_type=`明示で使う分には対応不要です)。

5. **各`_write_*`をXSDの`xs:sequence`と突き合わせる。**
   `_write_document`/`_write_protocol`/`_write_data`/`_write_event_log`/
   `_write_pnml`など、構造要素を書き出す関数それぞれについて、対応する
   complexTypeの`xs:sequence`(子要素の出現順序・出現数)が変わっていない
   かを確認してください。順序が変わっていれば、書き出し関数内で
   `ET.SubElement`を呼ぶ順序をその通りに直す必要があります。

6. **各`_read_*`も同様に確認する。** 読み込み側は特に影響を受けやすい
   箇所です。`_read_document`/`_read_protocol`/`_read_data`/
   `_read_event_log`などは`maiml_domain`の各クラスを
   `m.DocumentType(id=..., date=..., creators=..., ...)`のように具体的な
   キーワード引数で直接呼び出しています。手順2でクラスの必須引数が
   増減・改名されていれば、ここが真っ先に`TypeError`で壊れるので、
   その通りに引数を追従させてください。逆に**任意引数が増えただけ**の
   場合はエラーにはなりませんが、対応するXML子要素の読み書きをここに
   追加しない限り、その新フィールドは読み込み時に静かに失われます
   (往復で消える)。

7. **`_parse_scalar_text()`/`_format_value()`に新しいプリミティブ型が
   ないか確認する。** これらは`xsi_type.lower()`に対する固定の
   トークン一覧(`"boolean"`, `"datetime"`, `"base64binary"`,
   `"hexbinary"`, `"uuid"`, `"decimal"`, `"double"`/`"float"`,
   `"long"`/`"short"`/`"byte"`/`"int"`)で分岐しています。新XSDが上記に
   ない全く新しいプリミティブ型(例:`xs:anyURI`、`xs:language`など)を
   導入した場合は、ここに分岐を追加してください。

8. **ルート型・名前空間・`version`属性を確認する。** `maimlRootType`/
   `protocolFileRootType`のxsi:type名、`xmlns`のURI
   (`http://www.maiml.org/schemas`)、ルート要素の`version`属性の期待値
   が変わっていないかを確認してください。

9. **round-tripテストを実施する。** `dumps()`した結果を`loads()`で
   読み戻し、再度`dumps()`した結果が最初の出力とバイト単位で一致する
   ことを確認してください(既存のテストで使われているパターンと同じ
   です)。手順6で見落としたフィールドは、たいていここで最初に
   検出されます。

10. **生成した全XMLを新XSDで検証する。** 6つの実サンプルファイル
    (`tests/`配下のフィクスチャ、またはこのリポジトリで過去に検証した
    ESEMstandard/FSEMgold/DAFMgoldcorrected/CCORRELATION/AAFM系のような
    構造)を新しい`pymaiml.builders`/`serialization`だけで組み立て直し、
    `pymaiml.validation.validate()`がエラー0件で通ることを確認します。

11. **補足業務ルール(supplementary business rules)も実行する。**
    `pymaiml.validation`が実装しているMaiML AI Common Specification由来の
    ルール(`EVT-02`のlifecycle complete判定、`ref`参照先の型チェック、
    XES名前空間の厳密一致、秘匿禁止要素など)が、XSDの変更によって
    意味的に変わっていないか確認してください。`pymaiml.validation`は
    `maiml-schema-validator`スキルの検証スクリプトと同等のロジックを
    独立に実装したものなので、業務ルール自体が変わった場合は**両方**を
    更新してください(手順1のXSD本体3箇所と同じ理由で、片方だけ直すと
    食い違います)。

12. **`xsi:type`値は名前空間プレフィックスを解決しない、素の文字列比較で
    判定されていることに注意する。** `xsi:type`はXML Schema上`xs:QName`型
    であり、本来はプレフィックスが束縛する名前空間URIによって意味が決まる
    ため、`xsi:type="maimlRootType"`(デフォルト名前空間`xmlns=
    "http://www.maiml.org/schemas"`に依存)と`xsi:type="maiml:
    maimlRootType"`(`xmlns:maiml="http://www.maiml.org/schemas"`という
    明示的プレフィックス)はXMLの仕様上まったく同じ意味であり、実際に
    lxmlの`XMLSchema.validate()`でもどちらも合格することを確認済み。
    しかし`pymaiml.serialization`のルート型判定(`xsi_type ==
    "maimlRootType"`という直接比較)と、`pymaiml._xsi_registry.
    class_for_xsi_type()`(`property`/`content`の約70種のxsi:type
    すべてが対象)は、どちらもQName解決を行わずに素の文字列一致で実装
    されているため、`maiml:`のような明示的プレフィックス付きで書かれた
    ファイルは`loads()`時に「Unknown xsi:type」として読み込みに失敗する
    (実際に検証済み: `xsi:type="maiml:maimlRootType"`のファイルはXSD
    構造検証には合格するが、`pymaiml.serialization.loads()`は
    `ValueError`を送出する)。実サンプルファイル・pymaimlの書き出し処理
    自体は一貫して「デフォルト名前空間+プレフィックスなし」を使っている
    ため、pymaimlだけで完結する限り実害はないが、外部ツールが生成した
    (プレフィックス付きの)ファイルを読み込む可能性がある場合は、
    `_read_maiml_file`/`class_for_xsi_type()`側でQName解決
    (`etree.QName(...).localname`相当の処理)を追加する改修を検討する
    こと。XSD更新そのものとは独立した既知の制約だが、手順8(ルート型・
    名前空間の確認)や手順3(xsi_registryの全型検証)を行う際に、
    プレフィックス付き入力への対応要否も併せて検討するとよい。

上記を一通り終えたら、`CHANGELOG.md`に変更内容を記載し(依存先
`maiml-domain`のバージョンを上げること自体もSDKにとっての変更として
扱います)、破壊的変更かどうかに応じて`CHANGELOG.md`冒頭のバージョニング
ポリシーに従ってバージョンを上げてください。
