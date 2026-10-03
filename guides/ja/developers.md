# NarraLoom で構築する

[English](../developers.md) · [简体中文](../zh-CN/developers.md) · [日本語](developers.md)

Python バックエンドが作成、セッション、モデルオーケストレーション、ルール、永続化を担います。React は同じ HTTP API のリファレンスクライアントです。`python -m pip install .` でインストールし、`narraloom serve --workspace /path/to/my-game` を実行します。生成には `--models-config` を、ビルド済みフロントエンドをマウントするには `--web-dist` を指定します。

## バックエンドを埋め込む

```python
from pathlib import Path
from roleplay_world.app import create_app
from roleplay_world.config import AppConfig

app = create_app(config=AppConfig(
    workspace_root=Path("/path/to/my-game"),
    data_root=Path("saves"),
    output_root=Path("diagnostics"),
    models_config=Path("models.local.json"),
))
```

この ASGI アプリケーションを Uvicorn と単一ワーカーで配信します。`AppConfig` は相対パスをワークスペースに対して解決します。明示的な設定はプロセス全体の `RPW_*` パス設定とは独立しています。`model_config={...}` はインメモリ設定を提供します。[アーキテクチャ](../../docs/ARCHITECTURE.md) ではライターの所有権とモジュール境界について説明しています。

## HTTP または Python を使用する

インタラクティブな OpenAPI ドキュメントは `/docs` に、スキーマは `/openapi.json` にあります。まず `POST /api/session` で開始し、HttpOnly Cookie を保持し、返された CSRF トークンを書き込み時に `X-CSRF-Token` として送信します。ブラウザフロントエンドは同一オリジンまたは同一オリジンのリバースプロキシを使用する必要があります。

非同期の `roleplay_world.client.NarraLoomClient` がこれらの詳細を処理します。送信前に `Session` と各 `PreparedRequest` を保存してください。タイムアウトやプロセス再起動後にその保存済みリクエストを再利用して、同じジョブ、キャンペーン、アクションを復元します。実行のリトライは明示的です。完全な [SDK ガイド](../../docs/CLIENT.md) と [ヘッドレス例](../../examples/headless.py) を参照してください。

カスタムフロントエンドは `GET /api/studio/jobs/{id}` を通じて作成ジョブを追跡します。プレイでは、ブランチビューを読み取り、`expected_world_version` を添えてアクションを送信し、アクションスナップショットまたは SSE エンドポイントを追跡します。コミットされたナラティブと新しいビューを一緒に表示します。安定した機械可読なエラーコードが、古いバージョン、権限の失敗、モデルエラーを区別します。プロバイダの診断テキストは元の言語を保持する場合があります。

## モデルを拡張する

`builtin_engines()` に `Engine` を登録し、`registry=registry` を `create_app` に渡します。その非同期呼び出しは設定、生成または決定のペイロード、認証ヘッダーを受け取ります。生成は `text`、`model`、およびオプションの `usage` を返します。オプションの `probe` はトランスポート固有のヘルスチェックを提供します。

`examples/embedded_backend.py` は、決定論的なコントラクトフィクスチャを備えたネイティブ Python アダプターを示しています。アダプターはローカルライブラリまたはリモートサービスを呼び出すことができます。モデルの提案は提供されたスキーマ内に保ってください。[ENGINES](../../docs/ENGINES.md) では機能検証、予算、トレーシングについて説明しています。

`gateway=` を使用してゲートウェイ全体を置き換えるか、`avatar_factory(store)` を使用してプレゼンテーションサービスを提供します。これらのフックは正規の状態コミットをフレームワーク内に残します。新しいイベントタイプと永続化の実装には、コアコントラクトへのバージョン付き変更とリプレイテストが必要です。

## 数値判定を拡張する

`create_app(check_registry=...)` に `CheckRegistry` を渡し、技能・攻撃・反撃の決定論的な判定処理を登録できます。世界にはエンジンID、バージョン、設定値を固定します。組み込み実装は複数のダイスの合計に対応し、[check_engine.py](../../examples/check_engine.py) は成功数を数えるダイスプールの例です。

`GET /api/check-engines` で実装を確認し、`CreateWorld.check_engine` または `WorldBlueprint.check_engine` を設定します。コンテンツの自動テストで実装を検証し、確定記録にダイスと結果を保存するため、リプレイ・分岐・復元にも対応します。[判定エンジンのリファレンス](../../docs/CHECK_ENGINES.md) に登録、乱数、バージョン固定、パッケージ依存関係をまとめています。

## 記憶検索を拡張する

`memory_embedding` を `openai_embedding` のローカルサービスや API に接続するか、`embed` 能力を持つ Python `Engine` を登録します。`memory_policy.mode=hybrid` に設定すると、プランナーと NPC のコンテキストが意味検索を使用します。カスタムフロントエンドでは `client.recall(...)` で出典付きの記録を取得できます。[記憶 API](../../docs/MEMORY.md) にベクトル契約、視点、予算、キャッシュ、Transformers アダプターの例をまとめています。

## リファレンスフロントエンドで作業する

```bash
python -m pip install -e '.[dev]'
npm ci
npm run dev
```

Vite は `/api` をポート 18090 のバックエンドに転送します。`npm run build` でビルドします。カタログキー、パラメータ、ブラウザ設定は `npm run test:i18n` でチェックされます。[ローカリゼーション](../../docs/I18N.md)、[コントラクト](../../docs/CONTRACTS.md)、[テスト](../../docs/TESTING.md) を参照してください。
