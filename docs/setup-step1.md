# STEP 1・2 実機セットアップ

目的は「CoreS3の映像をPCブラウザへ表示する」ことだけです。人物AIはまだ入れません。

## 0. 先に既存環境をバックアップする

書き込みを行うと、現在のStack-chanプログラムは上書きされます。先に次の2種類を保存してください。

### A. 元のソースコード

現在のStack-chanファームウェアの元ソースを、別のGitリポジトリまたは複製フォルダへ保存してください。このPoCリポジトリには元の白猫ファームウェアは含まれません。

念のためFinderでフォルダごと複製する場合は、末尾に日付を付けます。

例:

```text
StackChan_original_2026-08-21
```

ソースから元の相棒AIへ戻せますが、端末内の設定も含めてそのまま戻せるよう、次のフラッシュ全体バックアップも行います。

### B. CoreS3のフラッシュ全体

1. CoreS3をUSB-CでMacへ接続する
2. このプロジェクト専用のPython環境を作る

```bash
cd ai-booth-analytics
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-tools.txt
```

3. 接続ポートを確認する

```bash
ls /dev/cu.*
```

接続前後で増えた `/dev/cu.usbmodem...` がCoreS3です。表示されない場合は、データ通信対応のUSB-Cケーブルへ替えます。

4. バックアップ先を作る

```bash
cd ai-booth-analytics
mkdir -p backups
```

5. `<PORT>` を実際のポート名に置き換えて、16MB全体を読み出す

```bash
.venv/bin/python -m esptool --chip esp32s3 --port <PORT> read_flash 0x000000 0x1000000 backups/stackchan-full-2026-08-21.bin
```

例:

```bash
.venv/bin/python -m esptool --chip esp32s3 --port /dev/cu.usbmodem101 read_flash 0x000000 0x1000000 backups/stackchan-full-2026-08-21.bin
```

6. ファイルサイズを確認する

```bash
ls -lh backups/stackchan-full-2026-08-21.bin
```

約16MBなら成功です。`backups/` はGit管理対象外で、認証情報を含む可能性があるため外部共有しません。

## 1. Wi-Fi情報を設定する

雛形をコピーします。

```bash
cd firmware/cores3-camera-stream
cp include/secrets.example.h include/secrets.h
```

`include/secrets.h` をテキストエディタで開き、次の2か所だけ変更します。

```cpp
constexpr char WIFI_SSID[] = "Wi-Fiの名前";
constexpr char WIFI_PASSWORD[] = "Wi-Fiのパスワード";
```

CoreS3は2.4GHz Wi-Fiを使います。会場Wi-Fiでは端末同士の通信が遮断される場合があるため、最初は自宅Wi-Fiかスマートフォンのテザリングを推奨します。

## 2. ビルドする

```bash
cd firmware/cores3-camera-stream
PLATFORMIO_CORE_DIR=../../.platformio-core ../../.venv/bin/pio run
```

`SUCCESS` と表示されればビルド成功です。

## 3. CoreS3へ書き込む

ここから既存プログラムが上書きされます。バックアップの16MBファイルを確認してから実行してください。

```bash
cd firmware/cores3-camera-stream
PLATFORMIO_CORE_DIR=../../.platformio-core ../../.venv/bin/pio run --target upload --upload-port <PORT>
```

通常の書き込みで認識されない場合は、CoreS3底面のRSTを長押ししてダウンロードモードへ入れ、もう一度実行します。

## 4. 映像を確認する

書き込み後、CoreS3の画面に次のようなURLが表示されます。

```text
http://192.168.1.23/
```

Macを同じWi-Fiへ接続し、そのURLをブラウザで開きます。mDNSが使えるネットワークなら次のURLでも開けます。

```text
http://stackchan-camera.local/
```

PC用確認画面を使う場合:

```bash
cd pc-viewer
python3 -m http.server 8080
```

ブラウザで `http://localhost:8080` を開き、CoreS3画面のIPアドレスを入力して「接続」します。

## 5. 合格チェック

- [ ] `/health` が `ok` を返す
- [ ] 映像が320×240で表示される
- [ ] 人が歩く様子を目視できる
- [ ] 30分間、CoreS3が再起動しない
- [ ] 映像を閉じて再接続できる

この5点が通ったら、STEP 3の人物検出へ進みます。

## 元のStack-chanへ戻す場合

復元はCoreS3のフラッシュ全体を上書きする操作です。対象ポートとバックアップファイルを再確認し、必要になった時点でCodexへ「バックアップから復元したい」と依頼してください。誤操作防止のため、ここでは自動実行しません。
