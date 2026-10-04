# オプションの 2D キャラクターを設定する

[English](../avatars.md) · [简体中文](../zh-CN/avatars.md) · [日本語](avatars.md)

この表示モジュールは任意で有効にします。まず[クイックスタート](quickstart.md)でテキストのキャラクターと物語を設定し、立ち絵を追加するときに以下を導入してください。

## 必要な機能を選ぶ

| 機能 | モデルとハードウェア |
| --- | --- |
| テキストの人物設定、世界、物語の生成 | 設定済みのテキストモデル API または推論サービス。バックエンドは CPU で動作 |
| 完成済み 2D 素材の表示 | `python -m pip install '.[avatar]'`、CPU バックエンド、WebGL ブラウザー |
| 参照画像から動く立ち絵を作成 | ソースの作成ワーカー、下記のローカル重み、Linux / WSL2 上の NVIDIA CUDA GPU |

完成した立ち絵を含むネイティブ世界パッケージを読み込み、世界のキャラクターエディターで選択します。新規作成は世界作成時に「動く 2D 立ち絵を追加（任意）」をオンにするか、「キャラクター素材」から参照画像を送り、完成後に割り当てます。立ち絵の生成中もテキストの作成やプレイを続けられます。

## ホストの要件

標準ワーカーは **x86-64 Linux または Windows WSL2**、**Python 3.11**、CUDA 12.6 対応の NVIDIA ドライバーと GPU を使用します。標準 4B 画像モデルでは、まず **VRAM 24 GiB、RAM 64 GiB** を計画の目安にしてください。実際のピークは画像サイズとオフロード設定に依存し、各段階は順番に動きます。小容量構成には個別の検証が必要です。重み、4 環境、キャッシュ、作業素材のために約 **70 GB** を確保し、導入前に空き容量を確認してください。

Windows は WSL2 と WSL 対応の NVIDIA Windows ドライバーを導入し、Ubuntu のシェルで実行します。WSL 内の `nvidia-smi` で GPU が見えることを確認し、コードと環境を Linux ファイルシステムに置きます。macOS は [CPU コンテナー](quickstart.md)、完成素材の読み込み、または Linux GPU ホストへの SSH 転送を利用できます。標準ワーカーは CUDA を使い、Apple Silicon MPS 用の作成アダプターは含まれていません。独立したリモート作成サービスは `avatar_factory` で統合できます。標準設定にはリモート作成 URL の切り替え項目はありません。

Ubuntu のシステム依存関係：

```bash
sudo apt-get update
sudo apt-get install -y git python3-venv libgomp1 libsndfile1 libportaudio2 sox
```

OS の Python が別バージョンなら Python 3.11 を別途導入します。専用の Conda Python 3.11 環境も利用できます。共有ホストでは環境配置と GPU スケジューラーの規則に従ってください。

## モデル一覧

| ロール | ダウンロード | 用途 |
| --- | --- | --- |
| `vision` | Qwen/Qwen3-VL-4B-Instruct | 参照画像の理解、外見と人物設定 |
| `image` | black-forest-labs/FLUX.2-klein-4B | 立ち絵と口形。標準でモデル CPU オフロード |
| `voice_design` | Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign | 現在のキャラクターパッケージに必要な声の参照素材 |
| `face_landmarker` | MediaPipe Face Landmarker | CPU で顔の特徴点を検出 |
| `segmentation` | BiRefNet-general ONNX | CPU で前景を抽出 |

リファレンス画面は**無音字幕と立ち絵アニメーション**を表示します。作成パッケージには声の参照素材も必要なため、このプリセットには VoiceDesign が含まれます。2D ルートでは 3D メッシュ生成を省き、AniGen、CosyVoice、Whisper の重みは不要です。立ち絵の生成は Qwen-Image-Edit-2511 に変更できますが、口形には引き続き FLUX を使います。[アダプター設定](../reference/avatars.md)を参照してください。

## ダウンロード

チェックアウトでバックエンド環境を有効にして実行します：

```bash
python -m pip install -e '.[avatar,download]'
narraloom models list
narraloom models download avatar-2d --model-root ./models --dry-run
narraloom models download avatar-2d --model-root ./models --mirror
```

`./models` は容量のあるディスクや既存の共有モデルディレクトリに変更できます。`--mirror` は Hugging Face リポジトリに中国向けミラー **https://hf-mirror.com** を使用します。省略すると公式サイト、`--endpoint https://your-hf-endpoint.example` で別の互換端点を選べます。各モデルはコミットに固定され、中断後は同じコマンドで再開できます。ファイルのメタデータと重みの SHA-256 を検証します。FLUX は Diffusers 形式のみを取得し、ルートの重複重みを省きます。`avatar-2d` を `vision` などの単一ロールに置き換えることもできます。`--dry-run` は正確なパスとバージョンだけを表示します。

標準では保存済みの HF token を送信しません。認証が必要なら非公開の環境変数を設定し、`--token-env HF_TOKEN` を明示します。選択した HF 端点へ送信されます。モデルのアクセス条件は事前に上流サービスで確認してください。

MediaPipe は Google、BiRefNet は rembg の GitHub Release から取得し、HF ミラーはこの 2 つを中継しません。別の取得先は `resource-urls.local.json` に `face_landmarker` または `segmentation` と URL の対応を書き、`--resource-urls resource-urls.local.json` で指定できます。固定ハッシュの検証は継続します。`--dry-run` のパスに検証済みファイルを置く方法も使えます。モデルファイルの検証に失敗した場合は、表示された破損ファイルを削除して再実行してください。

## 作成環境を導入する

インストーラーは指定ルートに **4 つの専用環境**を作成します。別用途の既存環境を保持し、2D 用の依存関係だけを導入して import と導入済みパッケージを記録します。固定 Qwen3-TTS ソースには Git 接続が必要です。CUDA wheel は PyTorch の配布サイトを使います。HF ミラー設定の対象はモデル重みです。

```bash
python scripts/install_avatar_envs.py --env-root ./.venvs/avatar --dry-run
python scripts/install_avatar_envs.py --env-root ./.venvs/avatar
narraloom models configure avatar-2d --model-root ./models --env-root ./.venvs/avatar --runner local
narraloom models check
narraloom serve --workspace . --web-dist web/dist
```

Python 3.11 で実行するか、`--python /absolute/path/to/python3.11` を指定します。`--only vision`、`--only face`、`--only portrait`、`--only qwen` で個別に導入できます。`models check` は重みを読み込まず、ファイルと実行ファイルのパスを確認します。GPU 推論と最終素材の確認は実際の作成で行います。

`models configure` は `configs/avatar.local.json` と `configs/avatar-models.local.json` に絶対パスと現在のバックエンド Python を保存します。既存設定は保持するため、既存モデルや環境を使う場合はファイルを編集してください。`runner: local` はホストの可視 GPU 上でジョブを直列実行します。GPUQ を利用する共有ホストでは `--runner gpuq` を選び、プロジェクト所有者として実行します。他のスケジューラーは実行アダプターで統合します。変更後はバックエンドを再起動してください。ソースの作成機能はチェックアウトをワークスペースとして使用し、独立インストールの wheel は完成素材を表示できます。

## 作成を確認する

正面が鮮明な PNG/JPEG/WebP 画像を使います。各辺 128 ピクセル以上、合計 2400 万ピクセル以下、10 MB 以下です。1 体を作成し、ジョブ状態を確認して NPC に割り当て、その NPC のいるシーンで立ち絵と確定した台詞による動きを確認します。失敗段階のログは `outputs/creations/<job-id>/` にあります。環境や素材を修正して既存ジョブを再試行します。作成時間には GPU の待機とモデル読み込みが含まれます。通常のプレイでは完成済み素材を再利用できます。

ダウンロード・設定 CLI はインストール済みバックエンドにも含まれ、取得には `download` extra を使います。環境インストーラーと作成ワーカーはソースに含まれます。[Roleplay Avatar](https://github.com/Toyhom/RoleplayAvatar) の固定ワーカーを使用し、出典と条件は [NOTICE](../../NOTICE.md) に記載しています。
