# PyMaiML

[![Tests](https://github.com/MaiML-Library/PyMaiML/actions/workflows/test.yml/badge.svg)](https://github.com/MaiML-Library/PyMaiML/actions/workflows/test.yml)

MaiML(JIS K 0200 / Measurement Analysis Instrument Markup Language)を
Pythonから扱うためのSDKです。

## MaiML-Domainとの関係

このSDKは、MaiML-Schema-1_0のcomplexTypeに1:1対応する純粋なデータモデルで
ある [MaiML-Domain](https://github.com/MaiML-Library/MaiML-Domain)
(`maiml_domain`パッケージ)の上に構築されています。

- `maiml_domain`: XSDに対応するデータクラス群を提供する、依存ライブラリ
  ゼロの基盤パッケージ。ただし「純粋なデータモデル」とはいえ完全に無検証
  ではなく、**XSD単体(1つのcomplexType定義)を見るだけで機械的に判断できる
  制約**(`minOccurs`/`maxOccurs`、`xs:choice`の排他性、required属性、
  `simpleType`の字句上の制約など)はコンストラクタが検証し、違反時には
  `ValueError`/`TypeError`を送出します。XMLシリアライズは持ちません。
- `pymaiml`(このリポジトリ): `maiml_domain`を依存パッケージ
  として取り込み、その上に以下を実装する層。
  - `.maiml`ファイルとの相互変換(シリアライズ/デシリアライズ)
  - **複数要素・複数セクションをまたいで初めて判断できる検証**
    (`id`/`ref`の整合性、`ref`参照先の型チェック、
    `lifecycle:transition="complete"`の必須化など、MaiML AI Common
    Specificationの業務ルール検証)
  - オブジェクトツリーを組み立てやすくする高レベルAPI

つまり境界線は「1つのcomplexType定義だけを見て判定できるか、複数要素を
またいで初めて判定できるか」で引いています。前者は`maiml_domain`のコンス
トラクタが即座に拒否すべき制約、後者は`pymaiml.validation.validate()`が
受け持つ制約です。新しい検証ロジックをどちらに実装すべきか迷ったら、まず
この基準に照らして判断してください。

`maiml_domain`自体をこのSDKやCLIツールと同じリポジトリに置かず、あえて
別リポジトリに分離しているのは、Python製のSDKやAPI/ツール層(将来追加され
うるもの)が`MaiML-Domain`を共通のドメインモデルとして利用し、モデル自体の
変更が1箇所の議論(Issue/PR)で完結するようにするためです(`maiml_domain`
自体はPythonの実装なので、他言語向けSDKを新設する場合はその言語向けに
ドメインモデルを別途実装することになり、本リポジトリのコードをそのまま
共有できるわけではありません)。

## インストール

```bash
pip install -e ".[dev]"
```

`pyproject.toml`の`dependencies`に`maiml-domain`がGit経由の依存として
指定されているため、`pip install`時に自動的に
`https://github.com/MaiML-Library/MaiML-Domain.git`の`v0.2.0`タグから
インストールされます。

```toml
dependencies = [
    "maiml-domain @ git+https://github.com/MaiML-Library/MaiML-Domain.git@v0.2.0",
]
```

### なぜ`main`ブランチではなく特定のタグを指定するのか

MaiML-Domainを`main`ブランチのまま参照すると、Domain側の将来の変更
(仕様追加・破壊的変更含む)がこちらに無断で流れ込んでしまいます。
バージョンタグ(`v0.2.0`など)に固定し、Domain側を更新したいときに明示的に
このバージョン指定を上げる、という運用にしてください。Domain側の
`CHANGELOG.md`と合わせて確認すると、何が変わったか追跡しやすくなります。

### ローカルでMaiML-Domainと同時に開発する場合

Domain側とSDK側を手元で同時に編集しながら動かしたい場合は、兄弟フォルダ
としてクローンした上でeditableインストールに切り替えると便利です。

**`pip install -e ../MaiML-Domain`の後に`pip install -e ".[dev]"`を続けて
実行しないでください。** `dependencies`の
`maiml-domain @ git+...@v0.2.0`はdirect URL指定であり、pipは既存の
editableインストールで要件が満たされているとは判断しません。そのため
2つ目のコマンドが1つ目で入れたeditable版を**エラーを出さずに**
アンインストールし、gitタグ`v0.2.0`から取得した固定版に静かに差し替えて
しまいます(Domain側を編集しても反映されない状態に陥り、気づきにくい
のが厄介な点です)。代わりに`--no-deps`を使い、依存(`lxml`/`pytest`)は
個別にインストールしてください。

```bash
pip install -e ../MaiML-Domain
pip install "lxml>=4.9" pytest
pip install --no-deps -e .
```

この手順なら`pyproject.toml`の変更は不要で、両方がeditableのまま
保たれます(`pip show maiml-domain`の`Location`がクローン先のパスに
なっていることで確認できます)。ただし、CI/リリースビルドでは
必ず上記のGit+タグ指定の依存関係(`pip install -e ".[dev]"`)を
使ってください。

## モジュール構成

- `pymaiml.serialization` -- `maiml_domain`のオブジェクトツリーと実際の
  `.maiml` XMLとの相互変換。書き出し(`dumps()`/`dump()`)・読み込み
  (`loads()`/`load()`)の両方向を実装済みです。
  `maiml_domain`の各property/content型はモジュール内のレジストリ
  (`_xsi_registry.py`)から自動生成されるxsi:type名で判定されるため、
  70種類ある型のうちどれを使っても個別対応は不要です。

  `loads()`/`load()`は`LoadedMaiml`(`root`/`namespaces`/`ids`の3属性を
  持つ)を返します。「既存のMaiMLファイル(protocolのみのテンプレート
  ファイルなど)を読み込み、`protocol`/`document`をそのまま引き継いで、
  新たな値で`data`/`eventLog`を組み立てて書き出す」というユースケースを
  想定しており、その際に必要な以下2点を`LoadedMaiml`が直接サポートします。

  - `namespaces` -- 読み込んだファイルのルート要素が宣言していた名前空間
    (`lifecycle:`など、`xsi`を除く)。書き出し時に
    `dumps(root, extra_namespaces=loaded.namespaces)`とそのまま渡せば、
    元のファイルの名前空間宣言を再現できます。
  - `ids` -- 読み込んだファイル内の全`id`値。新規要素の採番に使う
    `IdFactory`をこの値で初期化する(`IdFactory.from_existing_ids(loaded.ids)`)
    ことで、読み込んだファイルのidと衝突しない新しいidを安全に採番でき
    ます(`pymaiml.builders`の節を参照)。

  ```python
  from pymaiml import serialization
  from pymaiml.builders import IdFactory, new_complete_event
  import maiml_domain as m

  loaded = serialization.load("template_protocol.maiml")
  ids = IdFactory.from_existing_ids(loaded.ids)

  mt = loaded.root.protocol.material_templates[0]
  material = m.MaterialType(id=ids.new_id("material"), ref=mt.id,
                             content=m.GlobalObjectContent(uuid=ids.new_uuid()))
  # ... results/data/event/trace/log/eventLog も同様に組み立てる ...

  full_root = m.MaimlRootType(
      document=loaded.root.document, protocol=loaded.root.protocol,
      data=data, event_log=event_log,
  )
  serialization.dump(full_root, "measured.maiml", extra_namespaces=loaded.namespaces)
  ```

  **既知の制限:**

  - `loads()`はスキーマ妥当な入力のみを対象としています。必須要素が
    欠けたファイルは`maiml_domain`の各クラスがコンストラクタで基数
    (`minOccurs`)を検証する設計のため、その場で`ValueError`が発生して
    読み込みが止まります。壊れたファイルをオブジェクトとして開いて
    中身を調べたり、プログラムで修復したりする用途には現状対応して
    いません。ファイルの妥当性が不明な場合は、先に
    `pymaiml.validation.validate()`でエラー箇所を(1件ずつではなく)
    まとめて特定してください。
  - `document`に`Signature`(XML電子署名)を持つファイルは`loads()`で
    読み込めます(`loaded.root.document.signature`として文字列のまま
    保持され、検証等に利用できます)が、`dumps()`/`dump()`は既存の
    `Signature`を**常に**出力から除外します。原則として維持する手段は
    ありません。MaiMLの`<Signature>`はJIS X 5093 / ETSI TS 101 903
    (XAdES)準拠のenveloped署名であり、Digestは署名時点の厳密なバイト列
    に対して計算されます。`dumps()`はオブジェクトツリーから
    インデント・namespace宣言位置・属性順序・空要素表現などを含めて
    XMLを再構築するため、内容を一切変更していなくても元のバイト列を
    再現できる保証がなく、`pymaiml`自身は署名の生成・検証を実装して
    いません(CONTRIBUTING.md参照)。そのため、「内容が変わっていない
    から署名を維持してよい」という判断自体を`pymaiml`が行うことは
    安全性を保証できず、以前あった`drop_stale_signature=`引数
    (変更検出時のみ除外)は廃止し、常に除外する方式に変更しました。
    署名済みファイルが必要な場合は、`dumps()`/`dump()`で内容を確定させた
    「後で」、その出力バイト列に対して`maiml-signer`スキルなど専用の
    署名ツールで署名してください。
  - `loads()`は対象のXSD要素だけを明示的に拾ってDomainオブジェクトへ
    変換する設計であり、XMLコメント(`<!-- ... -->`)や処理命令
    (`<?...?>`)はモデル化していません。そのため`loads()`→`dumps()`で
    往復させると、元のファイルに含まれていたコメント・処理命令は
    失われます(XMLとして完全にlosslessなround-tripは保証していません)。
    これは単なる開発者向けメモの消失に留まりません。コメントが
    「データの一部を意図的に省略している」といった、それ自体が
    意味を持つ情報を担っている場合、その情報ごと失われる点に
    注意してください
    (XML comments and processing instructions are not preserved by
    load/dump round trips)。
- `pymaiml.validation` -- `.maiml`/`.maiml.zip`/`.mai`ファイルを、
  同梱の公式MaiML-Schema-1_0(`pymaiml/schema/`)とMaiML AI Common
  Specificationの補足ルール(`lifecycle:transition="complete"`の必須化、
  `ref`参照先の型チェック等)の両方で検証します。

  ```python
  from pymaiml.validation import validate
  result = validate("sample.maiml")
  assert result.ok, result  # result.errors / .warnings / .info も参照可
  ```

  > **注意: 同梱のXSDは公式配布版そのものではありません。**
  > `pymaiml/schema/MaiML-Schema-1_0/`のうち`maiml.xsd`/`maiml-core.xsd`/
  > `maiml-document.xsd`/`maiml-property.xsd`/`xenc-schema.xsd`の5本
  > (他13本中)には、公式配布版には無い`xs:import`(`xmldsig`/`xmlenc`
  > 名前空間)を追記しています。公式配布版はこれらのimportを欠いており、
  > そのままではlxmlでスキーマオブジェクトを構築できないための実務的な
  > 補完です。`<Signature>`/`<EncryptedData>`の内部構造まで検証する
  > ために必要な変更なので、公式配布版で上書きしないでください。
  > `maiml-schema-validator`スキルの`reference/MaiML-Schema-1_0/`にも
  > 同じ差分を適用した同一内容のコピーを保持しています(CONTRIBUTING.md
  > 参照)。
  >
- `pymaiml.builders` -- オブジェクトツリーを手で組み立てる際の定型作業を
  減らすヘルパー群。`IdFactory`(id/uuidの重複しない採番。
  `reserve()`/`from_existing_ids()`で既存ファイル読み込み後のid衝突を
  回避できる)、`infer_property()`/`infer_content()`(Pythonの値の型から
  property/contentクラスを推定)、`new_complete_event()`
  (`lifecycle:transition="complete"`イベントの組み立て)を提供します。

  `infer_property()`/`infer_content()`は既定でPythonの値(`value=`/
  `values=`)の型からxsi:typeを推定しますが、`protocol`要素の汎用データ
  コンテナ(材料テンプレートの想定物性値など)はほとんどの場合、値が
  まだ存在しないプレースホルダーです。xsi:typeはスキーマ上必須のため、
  値がない場合は`xsi_type=`(`maiml_domain`のクラス、または
  `"floatType"`のようなxsi:type名の文字列)で明示的に指定してください。
  `xsi_type=`・`value=`/`values=`のどちらも与えなかった場合はエラーに
  なります。

  ```python
  from pymaiml.builders import infer_property

  # protocol側: 値はまだ無いプレースホルダー -- xsi:typeだけ明示
  placeholder = infer_property("ex:temperature", xsi_type="floatType", units="degC")
  ```

  また、同じ`key`について`protocol`側のプレースホルダーと、対応する
  `data`側の実測値記録が異なるxsi:typeになってしまうと(例えば実測値が
  たまたま整数に見えるPythonの`int`だったために`intType`と推定されて
  しまう場合など)不整合になります。`XsiTypeRegistry`のインスタンスを
  `protocol`・`data`両方の`infer_property()`/`infer_content()`呼び出しに
  `registry=`として共有して渡すことで、同じ`key`は常に同じxsi:typeで
  組み立てられることを保証できます。

  ```python
  from pymaiml.builders import XsiTypeRegistry, infer_property

  registry = XsiTypeRegistry()
  placeholder = infer_property("ex:temperature", xsi_type="floatType", registry=registry)
  # ... 後で実測値が手に入ったとき ...
  measured = infer_property("ex:temperature", value=20, registry=registry)
  assert type(measured) is type(placeholder)  # 20 (int) でもfloatTypeになる
  ```

  > **注意: 同じ親要素内で同じkeyを複数回使う場合について。**
  > MaiML-Schema-1_0は`key`の一意性を(同じ親要素内であっても)一切
  > 強制していません(`genericDataContainerGroup`は`property*, content*`
  > というだけで、スキーマ全体を通して`key`に対する`xs:unique`/`xs:key`
  > 制約はありません)。そのため、たとえば同じ`<material>`の中に
  > `key="ex:temperature"`のpropertyを複数回(2回目の測定値、など)
  > 記録することはスキーマ上有効です。
  >
  > `XsiTypeRegistry`はこの場合でも、全ての出現が同じxsi:typeに解決さ
  > れる限り問題なく動作します(2回目以降の呼び出しは、既に登録済みの
  > 型をそのまま再利用するだけです)。ただし、同じkeyに対して**意図的に
  > 異なる**xsi:typeを与えたい場合(通常は想定しない使い方です)は、
  > その呼び出しでは`registry=`を渡さずに`infer_property()`/
  > `infer_content()`を呼んでください(shared-typeチェックの対象から
  > 外れます)。
  >

  `pymaiml.builders`にはもう1つ、`pymaiml.query.get_templates()`が返す
  Templateオブジェクトから、対応するInstanceオブジェクトを組み立てる
  `create_instance()`/`create_instances()`があります(責務分離は
  `query`が「対象を選ぶ」、`builders`が「選ばれたものを実体化する」)。

  ```python
  from pymaiml import query
  from pymaiml.builders import IdFactory, InsertionValue, create_instances

  xml_text = open("template_protocol.maiml", "rb").read()
  templates = query.get_templates(xml_text, instruction_id="instr-1")

  ids = IdFactory()
  instances = create_instances(templates, id_factory=ids)
  ```

  `create_instance(template, *, id, id_factory, template_instance_map=None,
  insertion_values=None)`は1つのTemplateから1つのInstanceを作る
  下位プリミティブです。Templateの実型(`MaterialTemplateType`/
  `ConditionTemplateType`/`ResultTemplateType`)から対応するInstance型
  (`MaterialType`/`ConditionType`/`ResultType`)を自動判定するため、種類
  ごとに別の関数を呼ぶ必要はありません。`template.id`は`instance.ref`に
  なり(これがInstanceが「どのTemplateの実体か」を表す方法です)、
  Instance自身の`id`/`content.uuid`はTemplateの値を流用せず常に新規生成
  します。`content.name`/`description`/`annotation`はそのままコピーし、
  `content.properties`/`content.contents`(および排他的な`encryption`)は
  `copy.deepcopy()`するため、生成後にInstance側を編集してもTemplate側は
  変化しません。`content.insertions`だけはそのままコピーせず、
  Instance用の新しい`InsertionType`として再生成します -- `insertion`は
  外部ファイルを指すため、Templateのプレースホルダーとは別物の`uri`/
  `hash`を`InsertionValue`で呼び出し側が指定する必要があります(`uuid`は
  省略時に新規生成、`format`は省略時にTemplate側から継承)。対応する
  `InsertionValue`が無い`insertion`があると`ValueError`になります。

  ```python
  from pymaiml.builders import InsertionValue, create_instance
  import maiml_domain as m

  instance = create_instance(
      template, id=ids.new_id("material"), id_factory=ids,
      insertion_values={
          "file://template-placeholder.csv": InsertionValue(
              uri="file://measured-001.csv",
              hash=m.HashType(value=b"...", method="SHA-256"),
          ),
      },
  )
  ```

  Templateの`templateRef`はInstanceでは`instanceRef`になりますが、単純に
  同じ文字列をコピーすることはできません(Template IDとInstance IDは別
  の値です)。`template_instance_map`(Template ID → Instance IDの対応表)
  で変換します。MaiML-Schema-1_0が定義する「`templateRef`(親が
  `materialTemplate`) → 同じ`materialTemplate`」というルールは、参照先が
  「親自身」ではなく「同じ*種類*の別のTemplate」であることを意味するため、
  Template Aが`templateRef`でTemplate Bを指す(自己参照ではない)構成は
  正常なケースとして扱います。

  複数Templateをまとめて実体化する場合は`create_instances(templates, *,
  id_factory, insertion_values=None, existing_instance_map=None)`を使い
  ます。あるTemplateが同じバッチ内の別のTemplate(リストの後ろにあるもの
  でもよい)を`templateRef`で参照していても正しく解決できるよう、
  (1)バッチ内の全TemplateのInstance IDを先に採番してから、(2)
  `template_instance_map`を組み立て、(3)その後で1つずつ`create_instance()`
  を呼ぶ、という2段階で処理します(`create_instance()`自身は
  `template_instance_map`の構築を行いません -- あるTemplateを処理して
  いる時点では、参照先TemplateのInstance IDがまだ決まっていない可能性が
  あるためです)。`existing_instance_map`を渡すと、今回のバッチに含まれ
  ない(以前の呼び出しで既にInstance化済みの)Templateへの参照も解決でき
  ます(同じTemplate IDが両方にある場合は今回のバッチ側が優先されます)。
  同じTemplateを`templates`に2回以上含めることはできず、`ValueError`に
  なります。解決できない`templateRef`がある場合も`ValueError`になり、
  Template IDをそのままInstance IDとしてコピーするような黙った代替動作は
  しません。

- `pymaiml.query` -- ファイル内の「一覧」を取得する読み取り専用ユーティリティ
  群です。`get_uuids()`/`get_keys()`/`get_insertion_uris()`は
  `pymaiml.serialization.loads()`を呼び、その結果の`maiml_domain`オブジェクト
  ツリー(`loaded.root`)から値を拾います -- 生XMLを直接走査する独自実装は持たず、
  `serialization.py`が実際に読み書きする内容と食い違う心配がありません。その
  ため、この3関数に渡すXMLはスキーマ妥当である必要があります(`maiml_domain`の
  コンストラクタが要求するカーディナリティを満たさない場合は、`loads()`と同じ
  例外がそのまま送出されます)。`get_namespaces()`だけは例外で、今も生XMLを
  直接解析します(名前空間宣言は`maiml_domain`のオブジェクトツリーにはそもそも
  存在しない情報のためです)。

  ```python
  from pymaiml import query

  xml_text = open("sample.maiml", "rb").read()
  query.get_uuids(xml_text)           # -> List[str]  (uuid値、重複含む全件)
  query.get_keys(xml_text)            # -> List[str]  (key=属性値)
  query.get_namespaces(xml_text)      # -> Dict[str, str]  ({接頭辞: URI})
  query.get_insertion_uris(xml_text)  # -> List[str]  (InsertionType.uri)
  ```

  4関数とも出現順を保持しますが、重複の扱いは`get_uuids()`だけ異なります。
  `get_keys()`/`get_insertion_uris()`/`get_namespaces()`は重複を除去した
  結果を返します(`get_namespaces`は`dict`なので、キーの挿入順がそのまま
  出現順になります)。一方`get_uuids()`は重複を除去せず、見つかったuuidを
  全件そのまま返します。`uuid`は本来オブジェクトを一意に識別するためのもの
  なので、同じ値が複数回出現すること自体が検出したい事実になり得るためです
  (重複除去した一覧が欲しい場合は呼び出し側で`set(...)`や
  `dict.fromkeys(...)`を使ってください)。

  `get_uuids()`/`get_keys()`/`get_insertion_uris()`は、`maiml_domain`の各
  クラスの`__init__`が属性を代入する順序をそのまま辿る、クラスの種類に依存
  しない汎用的な木構造の走査(`vars(obj)`を再帰的に辿る)で値を集めます。
  そのため`maiml_domain`が将来クラスを追加しても、この3関数側を追随させる
  必要がありません。`get_uuids()`は`uuid`属性を持つあらゆるオブジェクト
  (`GlobalObjectContent`の識別uuid・`InsertionType`のuuid・`ChainType`/
  `ParentType`のuuid)をまとめて拾い、`get_keys()`も同様に`key`属性を持つ
  あらゆるオブジェクト(`property`/`content`の各具象クラス、`ChainType`/
  `ParentType`)をまとめて拾います。`get_insertion_uris()`は
  `InsertionType.uri`だけを集めます -- `InsertionType`は`uri`を必須にして
  いるため、URIを持たない`insertion`という不正な形はそもそも構築できません。

  `get_namespaces()`は`LoadedMaiml.namespaces`(ルート`<maiml>`要素のみ走査)
  とは異なり木全体を走査するため、`pymaiml`の`dumps()`を経由していない
  外部生成ファイル(例: ルート以外の要素に`xmlns:ds`を宣言したまま署名された
  ファイル)でも正しく名前空間を検出できます。同じ接頭辞に異なるURIが束縛
  されている場合は`ValueError`を送出します。

  `get_uuids()`/`get_keys()`/`get_insertion_uris()`のXXE/entity-expansion/
  networkハードニングは、内部で呼び出す`pymaiml.serialization.loads()`の
  ものがそのまま適用されます(これら3関数はもう生XMLを自前で解析しません)。
  `get_namespaces()`は今も`pymaiml._xml_security.make_untrusted_input_parser()`
  で直接解析するため、同等のハードニングを維持しています。

  上記4関数(文字列のフラットな一覧を返す)とは別に、`get_templates()`/
  `get_instances()`という2関数があります。こちらは文字列ではなく
  `maiml_domain`のオブジェクトそのものを返し、キーワード引数でフィルタする
  設計です(「id だけ欲しい」場合は関数を分けず、返ってきたオブジェクトから
  呼び出し側で`.id`を取り出すだけで済みます)。両関数とも
  `pymaiml.serialization.loads()`を経由するため、上記3関数と同じくXMLは
  スキーマ妥当である必要があります。戻り値の型ヒントは`List[object]`では
  なく、`query.Template`(`MaterialTemplateType`/`ConditionTemplateType`/
  `ResultTemplateType`の`Union`)・`query.Instance`(`MaterialType`/
  `ConditionType`/`ResultType`の`Union`)という具体的な型エイリアスで
  表現しています。

  ```python
  from pymaiml import query

  xml_text = open("sample.maiml", "rb").read()

  # テンプレート一覧(material/condition/resultTemplateの実体そのもの)
  query.get_templates(xml_text)                            # -> 全種類
  query.get_templates(xml_text, kind="material")            # -> materialTemplateのみ
  query.get_templates(xml_text, instruction_id="instr-1")   # -> ある instruction にPNML経路で紐づくものだけ

  # インスタンス一覧(material/condition/resultの実体そのもの)
  query.get_instances(xml_text)                            # -> 全種類
  query.get_instances(xml_text, kind="result")              # -> resultのみ
  query.get_instances(xml_text, instruction_id="instr-1")   # -> ある instruction に紐づくものだけ

  # id だけ欲しい場合は呼び出し側で取り出す -- 専用関数はない
  [t.id for t in query.get_templates(xml_text)]
  ```

  `kind=`は`"material"`/`"condition"`/`"result"`のいずれかで、指定しなければ
  (`None`、既定値)3種類まとめて返します。未知の`kind`を渡すと`ValueError`に
  なります。

  `instruction_id=`は`get_templates()`/`get_instances()`の両方にあります。
  共通の経路は、指定した`<instruction id=...>`の`transitionRef`が指す
  `<transition>` → その`<transition>`に触れる`<arc>` → その`<arc>`の
  もう一方の`<place>` → その`<place>`を`placeRef`で指すテンプレート、という
  PNMLトポロジー経由の連鎖です。各段階は`id`文字列同士が一致するだけでは
  なく、対応する`maiml_domain`オブジェクト(実在する`TransitionType`・
  `PlaceType`)が実際に存在することも確認します -- `maiml_domain`自体は
  IDREFの解決可能性を保証しないため(MaiML-Schema-1_0のXSDのような強制は
  ありません)、たまたま一致した文字列だけでテンプレートに辿り着かない
  ようにするためです(「Domainを問い合わせて答える、文字列一致で答えない」
  というPyMaiMLの設計方針に沿っています)。`get_templates()`はここで止まり、その
  テンプレートを返します。`get_instances()`はさらにもう1段、そのテンプレート
  を`ref`で指すインスタンスまで辿ります。加えて`get_instances()`だけは、
  もう1つの独立した経路 -- `instruction` → (`ref`で参照する)`event` →
  `event`の`results_refs` → `results` → `results`の
  `materials`/`conditions`/`results` -- で見つかるインスタンスも**和集合**
  として合流させます(両方の経路から見つかったインスタンスは1回だけ
  列挙されます)。前者(PNML経路)は「このinstructionの遷移が配線上どの
  テンプレートに繋がっているか」、後者(event経路)は「このinstructionの
  実行が実際に記録したインスタンスは何か」という、それぞれ独立した問いに
  答えるものです。

  いずれの関数でも、指定した`instruction_id`がファイル内のどの
  `<instruction>`にも一致しない場合は`ValueError`になります(タイプミスを
  黙って`[]`にせず、はっきり検出するためです)。一方、`instruction_id`自体は
  実在するが、いずれの経路からも何も見つからない場合は`ValueError`では
  なく`[]`を返します -- この2つは意図的に区別されています。

  PNML経由の連鎖は`<protocol>`側だけで完結するため、`get_templates()`は
  `protocolFileRootType`(`<data>`/`<eventLog>`を持たない手法単体ファイル)
  でも`instruction_id=`を含めて通常どおり動作します。一方`get_instances()`
  は、テンプレートまでは辿れてもインスタンスの実体自体がそもそも存在
  しないため(`<data>`が無い)、`instruction_id`の有効・無効を問わず常に
  `[]`を返します(実在する`instruction_id`を渡してもエラーにはならず、
  単に返せるインスタンスが無いだけです)。

## テスト

```bash
pip install -e ".[dev]"
pytest
```

`tests/test_smoke.py`は`maiml_domain`への依存解決を確認する最小限の
スモークテストです。`tests/test_serialization.py`・
`tests/test_validation.py`・`tests/test_builders.py`が上記3モジュールの
実際の動作(スキーマ検証を通ることや、既存protocolを読み込んで
data/eventLogを追加するユースケースの実際の流れを含む)を検証します。

## ライセンス

Apache-2.0。詳細は[LICENSE](LICENSE)を参照してください。

## Contributing

MaiML仕様(業務ルール・シリアライズ形式など)に影響する変更は、必ず
GitHub Issue/PRでの議論を経てから行い、`CHANGELOG.md`に記載してください。
組織全体の方針は
[MaiML-Library/.github](https://github.com/MaiML-Library/.github/blob/main/profile/README.md)
を参照してください。

MaiML-Schema-1_0が更新された際に確認すべき手順(XSD反映箇所、
`pymaiml._xsi_registry`/`pymaiml.builders`/`pymaiml.serialization`各層への
影響範囲、round-tripテスト、supplementary business rulesの再確認など)は
[CONTRIBUTING.md](CONTRIBUTING.md)にチェックリストとしてまとめています。
XSD変更を伴う作業を行う場合は、必ず参照してください。
