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

## リファレンスフロントエンドで作業する

```bash
python -m pip install -e '.[dev]'
npm ci
npm run dev
```

Vite は `/api` をポート 18090 のバックエンドに転送します。`npm run build` でビルドします。カタログキー、パラメータ、ブラウザ設定は `npm run test:i18n` でチェックされます。[ローカリゼーション](../../docs/I18N.md)、[コントラクト](../../docs/CONTRACTS.md)、[テスト](../../docs/TESTING.md) を参照してください。
