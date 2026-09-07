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

- `pymaiml.validation` -- `.maiml`/`.maiml.zip`/`.mai`ファイルを、
  同梱の公式MaiML-Schema-1_0(`pymaiml/schema/`)とMaiML AI Common
  Specificationの補足ルール(`lifecycle:transition="complete"`の必須化、
  `ref`参照先の型チェック等)の両方で検証します。
  ```python
  from pymaiml.validation import validate
  result = validate("sample.maiml")
  assert result.ok, result  # result.errors / .warnings / .info も参照可
  ```
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
