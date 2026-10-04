# クイックスタート

[English](../quickstart.md) · [简体中文](../zh-CN/quickstart.md) · [日本語](quickstart.md)

世界、物語、**テキストの NPC 設定**はモデル API で生成でき、バックエンドは CPU で動作します。**参照画像から動く 2D 立ち絵を新規作成**する場合は、別のローカルモデルと CUDA GPU が必要です。**完成した素材の読み込み**には `avatar` extra を使います。[2D 設定とモデルダウンロード](avatars.md)を参照してください。

## OS ごとの実行方法

| コンピューター | バックエンド | 新しい 2D 立ち絵の作成 |
| --- | --- | --- |
| Linux | 下記 Python 手順、または Linux コンテナー | x86-64 ホスト、NVIDIA CUDA、[作成環境](avatars.md) |
| Windows | WSL2 Ubuntu、または Docker Desktop の Linux コンテナー | NVIDIA GPU 対応の WSL2 内で作成環境を導入 |
| macOS、Intel / Apple Silicon | Docker Desktop の Linux コンテナー、またはリモート Linux | Linux NVIDIA ホストを利用。Mac ブラウザーで完成素材を表示可能 |

現在のバックエンドは Linux の書き込みロックを使用します。Windows は `wsl --install -d Ubuntu-24.04` を実行し、必要に応じて再起動してから Ubuntu 端末で Linux 手順を実行します。ブラウザーはいずれの OS でも利用できます。

## Linux / WSL2 のインストール

Python 3.11+ と Node.js 20+ を使用し、Linux シェルで実行します：

```bash
git clone https://github.com/Toyhom/NarraLoom.git
cd NarraLoom
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[avatar]'
npm ci
npm run build
narraloom serve --workspace . --web-dist web/dist
```

**http://localhost:18090** を開き、英語、簡体字中国語、日本語を選びます。**Ctrl+C** で前景のサービスを停止し、同じ `narraloom serve` コマンドで再起動します。開発時は `.[dev]` でテストツールを導入できます。

## macOS / Docker Desktop

Git と Docker Desktop を導入し、Docker を起動して Terminal で実行します。Linux コンテナーを有効にした Windows PowerShell でも同じコマンドを使用できます：

```bash
git clone https://github.com/Toyhom/NarraLoom.git
cd NarraLoom
docker build -t narraloom .
docker run -d --name narraloom --hostname narraloom -p 127.0.0.1:18090:18090 -v narraloom-workspace:/workspace narraloom
```

**http://localhost:18090** を開いて UI から API を設定します。イメージにはバックエンド、ビルド済みフロントエンド、完成素材の表示機能が含まれます。名前付きボリュームにセーブと設定を保存します。1 ボリュームにつき 1 コンテナーを使い、再作成時も hostname を維持してください。停止は `docker stop narraloom`、再開は `docker start narraloom`、ログは `docker logs --tail 80 narraloom` です。初回ビルドでは Python/Node の依存関係を取得します。GPU 作成機能は Linux/WSL2 ホストで別途設定します。

Docker Desktop ホスト上のモデルには `http://host.docker.internal:<port>/v1` を使います。コンテナー内の `127.0.0.1` はコンテナー自身です。Linux Docker は `docker run` に `--add-host host.docker.internal:host-gateway` を加え、そのインターフェースからモデルサービスへ接続できるようにします。

## リモート Linux ホストを使う

サーバーで導入・起動してから、手元の Windows、Mac、Linux で実行します：

```bash
ssh -N -L 18090:127.0.0.1:18090 user@your-server
```

**http://localhost:18090** を開きます。転送端末は起動したままにしてください。Ctrl+C はトンネルだけを閉じ、サーバーは動作を続けます。

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
