# モデルの選択と設定

[English](../models.md) · [简体中文](../zh-CN/models.md) · [日本語](models.md)

最もシンプルな構成では、OpenAI 互換エンドポイントを通じて 1 つの強力な指示モデルを使用します。DeepSeek の `deepseek-flash` は動作する例です。プロバイダーが告知するモデル ID を使用してください。vLLM、SGLang、llama.cpp のエンドポイントは、同じプロトコルを通じてローカルチェックポイントを提供できます。

| モジュール | 有用なモデル特性 |
| --- | --- |
| `world_builder`、`story_builder`、`import_builder` | 構造化生成、長いコンテキスト、一貫した設定とアウトライン |
| `rules_builder`、`state_builder`、`simulation_builder` | 信頼性の高い JSON、条件、因果推論 |
| `content_reviewer`、`game_master` | 強力な指示追従と現在状態に関する推論 |
| `character_actor`、`narrator` | コンテンツ言語におけるキャラクターの声、対話、散文 |
| `world_actor` | NPC の知識と利用可能な行動を尊重する範囲内の提案 |
| `action_router` | System One 意思決定プロトコル。あなたの行動分布における測定済み精度 |
| `memory_embedding` | BGE-M3 など、コンテンツの言語に対応する埋め込みモデル。ローカル/API と Python `embed` アダプターに対応。[記憶の設定](../../docs/MEMORY.md) |
| 決定論的ルール | エンジンコードがダイス、算術、所有権、永続化を処理 |
| アバター表示 | 別途の画像/リグ作成、またはインポート済みの既製アセット。[Avatar](../../docs/AVATARS.md) を参照 |

より小さな対話モデルはコストを削減できます。それらの構造化出力とキャラクター挙動を、メインプランナーとは別に評価してください。一般的な小型モデルは、通常、ワールド生成と複雑なルールについてより多くのテストを必要とします。

## OpenAI と Anthropic のネイティブ API

モデル設定の **API プロトコル**で OpenAI Chat Completions、OpenAI Responses、Anthropic Messages を選択します。サービスのベース URL、アカウントで利用できるモデル ID、API キーを入力し、保存して接続をテストします。Responses は `https://api.openai.com/v1`、Messages は `https://api.anthropic.com/v1` を使います。名前付きプロバイダーにも同じ選択肢があり、創作・計画・対話を別々のサービスに割り当てられます。

Anthropic の **JSON Schema** モードは指定ツールで構造化結果を返します。Object とプロンプトモードはプロンプトで JSON を要求します。モデルが既定のサンプリング設定を必要とする場合は、**モデルの既定の温度を使う**を有効にします。[設定例](../../configs/models.native.example.json)と[トランスポート仕様](../../docs/ENGINES.md#generation-protocols)に設定ファイルとプロバイダー固有のパラメーターを示しています。

## サーバー設定

これを `configs/models.local.json` として保存し、`RPW_API_KEY` をシェルまたはサービス管理ツール内で非公開に設定してください：

```json
{
  "default": {
    "url": "https://api.deepseek.com/v1",
    "model": "deepseek-flash",
    "api_key_env": "RPW_API_KEY",
    "json_object": true,
    "timeout_s": 90
  },
  "roles": {
    "world_builder": {"max_tokens": 6000},
    "story_builder": {"max_tokens": 6000}
  }
}
```

ローカルサービスの場合、`url` を到達可能なアドレス（例：`http://127.0.0.1:8000/v1`）に設定し、その提供されるモデル名を使用してください。URL はバックエンドホストから到達されます。各ロールは独自のプロバイダー、モデル、タイムアウト、出力制限、生成パラメータを持つことができます。`json_object`、`json_schema`、プロンプトベースの JSON はプロバイダーのサポートに依存します。すべての結果は依然としてランタイム検証を通過します。

参照フロントエンドは、**モデルと使用状況** の下で名前付きプロバイダーとモジュールバインディングを公開します。モジュールチェックを実行する前に設定を保存してください。空のキーは同じエンドポイントの保存済みキーを保持します。それを削除すると、明示的なクリアコントロールが使用されます。[Engine contracts](../../docs/ENGINES.md) は、デプロイメントファイル形式と Python 拡張 API について説明しています。

## オプションの System One / Jev

System One は、型付きの `choice`、`noul`、`score` の質問を処理します。バンドルされたアダプターは Jev スタイルの意思決定サーバーをサポートします。`configs/models.hybrid.example.json` を出発点として、それを `action_router` にバインドしてください。

ルーティングはデフォルトで **off** です。**Shadow** は分類を記録しますが、メインプランナーが依然としてそのターンを処理します。**Auto** は、確率とマージンのしきい値を通過した場合に、明示的な単一の移動をルーティングできます。シャドウモードで開始し、auto を有効にする前に、否定、曖昧性、複数ステップの行動、言語のバリエーションを評価してください。しきい値はモデル出力です。ホールドアウトケースで実際のエラーを測定してください。

ローカルモデルのメモリは、重み、コンテキスト、量子化、並行性に依存します。オプションの推論は別の環境で実行し、同じ重みを使用するロール間でエンドポイントを共有し、ホストの GPU スケジューラに従ってください。通常の API バックエンドには GPU も Torch も不要です。固定された Jev セットアップコマンドは [ENGINES](../../docs/ENGINES.md) にあります。
