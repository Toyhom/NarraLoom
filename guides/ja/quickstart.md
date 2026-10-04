# クイックスタート

[English](../quickstart.md) · [简体中文](../zh-CN/quickstart.md) · [日本語](quickstart.md)

API ベースのセットアップでは、フレームワークを CPU マシン上で実行します。ローカルモデルのセットアップでは、同じバックエンドを推論サーバーに接続します。まずはすべての生成ロールに対して 1 つの高性能な指示モデルから始め、最初のストーリーが動作した後にロールを分割してください。

## インストール

Python 3.11+ を使用し、リファレンスフロントエンドには Node.js 20+ を使用します：

```bash
git clone https://github.com/Toyhom/NarraLoom.git
cd NarraLoom
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
npm ci
npm run build
narraloom serve --workspace . --web-dist web/dist
```

Windows では、PowerShell で `.venv\Scripts\Activate.ps1` を使用してアクティベートします。**http://localhost:18090** を開いてください。言語セレクターでは英語、簡体字中国語、日本語を選択できます。

## モデルの接続

**モデルと使用状況** を開き、OpenAI 互換のベース URL、プロバイダーの正確なモデル ID、および API キーを入力します。ローカルの認証不要エンドポイントでは、キーを空のままにできます。サポートされている JSON モードを選択し、保存してから接続をテストします。[Models](models.md) では、モジュールごとのバインディングとプロバイダーの例を説明しています。

ブラウザーの設定はそのセッションに属します。サーバー全体のデフォルトを設定するには、`configs/models.example.json` を `configs/models.local.json` にコピーし、そのエンドポイント/モデルを編集して、バックエンドを起動する前に `api_key_env` で指定された環境変数を設定します。ファイル設定を再読み込みするには再起動してください。プロバイダーが要求する場合は、ベース URL の `/v1` を保持してください。

## 作成とプレイ

1. **自分の世界を作成** を選択します。単一シーン、短編ストーリー、または探索アドベンチャーを選び、コンテンツ言語を設定します。
2. 設定を説明し、必要に応じて最初のストーリーも記述します。生成により編集可能な場所、キャラクター、アウトラインが作成され、その後ストーリーがチェックおよびプレイテストされます。
3. 現在のリビジョンが合格したら、プレイヤーに名前を付けて開始します。レポートが失敗した場合は、説明を確認し、編集するか AI によるリビジョンをリクエストして、再度テストします。
4. 話す、調査する、移動する、または待機します。エンジンは結果を記録します。世界に戻って別のストーリーを作成できます。

組み込みの Fogharbor アドベンチャーはホームページから利用できます。コミュニティのスターターは編集可能なコピーになり、独自のテストを実行します。生成とプレイテストは、お使いのモデルプロバイダーとその課金を使用します。

## バックエンドのみ

```bash
python -m pip install .
narraloom serve --workspace /path/to/my-game --models-config /path/to/models.local.json
```

API については **http://localhost:18090/docs** を開くか、チェックアウトから `python examples/headless.py --world 'A quiet reading room' --preset scene --language en` を実行します。この例ではセッションと保留中のリクエストが保存され、`--resume` でそれらを継続します。[developer guide](developers.md) を参照してください。

接続に失敗した場合は、エンドポイント、モデル ID、認証、JSON モードを確認してください。ストーリーテストに失敗した場合は、ジョブレポートを開いてください。接続の成功はモデルプロトコルを確認するだけです。[Deployment](deployment.md) では、リカバリーとバックアップについて説明しています。

[リファレンス画面](workspace.md)
