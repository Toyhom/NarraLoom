# モデル研究と評価

[English](../research.md) · [简体中文](../zh-CN/research.md) · [日本語](research.md)

NarraLoomはモデルの責務を個別に公開しているため、ストーリーゲームシステムの他の部分を固定したまま1つのモジュールを変更できます。有用な比較には、プランナーの精度、NPCの声、ナレーションの一貫性、コンテンツ生成品質、意思決定コストが含まれます。

## 比較を定義する

1. 1つのタスクと1つのモジュールを選びます。世界/ストーリーのリビジョン、プロンプト、ルール、初期状態、その他のモジュール設定は固定したままにします。
2. ベースライン構成を保存し、`providers`と`bindings`を通じて候補をバインドするか、Pythonエンジンを登録します。
3. コントラクトテストを実行し、その後モデルを利用したワークフローを実行します。失敗した出力、修復、レイテンシ、報告されたトークン使用量を結果の一部として記録します。
4. 新しい入力はホールドアウトケースで評価します。主観的な文章とプレイアビリティの判断には独立したプレイスルーを使用します。

モジュールごとのトレースは、要求されたモデル、応答モデル、デプロイリビジョンラベル、レイテンシ、使用量を記録します。プロバイダーのリビジョンラベルは実験者が提供するメタデータです。生の診断情報にはストーリープロンプトやシークレットが含まれる可能性があります。共有する前にデータを選択して匿名化してください。

## 固定入力によるモジュール評価

`python -m pip install '.[research]'` で研究用の依存関係をインストールします。入力を一度保存し、同じタスクを各モデル構成で実行します。

```bash
python examples/make_evaluation_cases.py --output outputs/evaluation/cases.jsonl
narraloom evaluate --cases outputs/evaluation/cases.jsonl \
  --models-config configs/baseline.local.json --output outputs/evaluation/baseline
narraloom evaluate --cases outputs/evaluation/cases.jsonl \
  --models-config configs/candidate.local.json --output outputs/evaluation/candidate
narraloom compare outputs/evaluation/baseline/report.json \
  outputs/evaluation/candidate/report.json --output outputs/evaluation/comparison.json
```

サンプルには英語・中国語・日本語の計12タスクが含まれます。プランナーは明示的な条件で採点し、NPCの会話とナレーションは人による評価用に保存します。同じAPIで生成、System Oneの意思決定、登録済みPythonエンジンを評価できます。正解条件はモデルへの入力や修復プロンプトから分離されています。

レポートには失敗、修復回数、所要時間、プロバイダーが返したトークン数と使用量の欠落を記録します。`--resume` は既存の結果を保持し、未実行のタスクを続行します。形式、指標、再開方法、独自アダプターについては[評価APIのリファレンス](../../docs/EVALUATION.md)を参照してください。

## 意思決定モデル

```bash
python scripts/evaluate_decisions.py   --url http://127.0.0.1:18110/v1   --model YOUR_DECISION_MODEL   --revision YOUR_REVISION   --output outputs/validation/decision-comparison
```

含まれている診断セットには42件の作成された中国語/英語のケースがあり、それぞれが逆順の終了順序で繰り返されます。レポートには、有効な応答、エンドツーエンドの精度、Brierスコア、キャリブレーションビン、自動カバレッジ/エラー、順序感度、レイテンシが含まれます。閾値選択用に別のデータセットを作成し、報告用にホールドアウトセットを作成してください。

`python scripts/evaluate_generation_router.py --output outputs/validation/generation-comparison`は、設定された生成モデルを同じルーティング入力に適用します。そのカテゴリ別結果は精度/レイテンシ/トークンの比較をサポートしますが、生成応答はキャリブレーションされた確率を提供しません。

## エンドツーエンドの動作

```bash
python scripts/verify.py --distribution
python scripts/check_distribution.py --output outputs/validation/sdk-model-check   --sdk-live --live-models-config configs/models.local.json --secrets-root secrets
```

ライブのインストール済みパッケージチェックは、世界と2つのストーリーを作成し、それらの自動テストを実行し、1ターンをプレイし、バックアップを復元し、再起動後のリクエスト回復を検証します。`scripts/check_longrun.py`はより長いアクションシーケンスを実行します。シナリオと出力ディレクトリについてはその引数を確認してください。

決定論的リプレイはイベント/永続化の動作をチェックします。コントラクトフィクスチャはソフトウェア境界を分離します。実モデルチェックは、実行されたタスクで選択されたモデルを測定します。対話、エージェンシー、ストーリー品質を評価する際は、これらを人間による評価と組み合わせてください。[Testing](../../docs/TESTING.md)には焦点を絞ったスイートが一覧されています。[engine contracts](../../docs/ENGINES.md)ではトレースとアダプターについて説明しています。

## 再開できるキャンペーンテスト

`narraloom playtest --source story.json --plan plan.json --models-config models.local.json --output outputs/playtests/run` で一連の行動を実行できます。計画には行動、モデルへ渡さない評価条件、人物や履歴バージョンごとの記憶検索を指定します。`--max-steps` でチェックポイントを保存し、`--resume` で確定済みの行動を復元します。失敗した行動の再実行には `--retry-failed` を追加します。形式、ネイティブアダプター、使用量の記録は[キャンペーンテスト](../../docs/PLAYTESTING.md)を参照してください。
