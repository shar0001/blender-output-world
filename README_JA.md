# OUTPUT WORLD 自動構築システム / README（日本語）

ストーリーボード後半3カット **06 OUTPUT EMERGENCE / 07 DIVE THROUGH OUTPUT /
08 HERO REVEAL** を制作するための、再実行可能な Blender 自動構築システムです。

1個の角丸 Cube を **Geometry Nodes** でインスタンス化し、青いブロック群からなる
巨大な OUTPUT フィールドを構築します。**個別オブジェクトは生成しません**
（数百〜数千個の Cube を作らず、GN のインスタンスで軽量に表現します）。

---

## 1. 必要環境

- **macOS**（Windows / Linux でも動作しますが、パス例は macOS 基準です）
- **Blender 4.x 推奨**（3.4 以上で概ね動作します）
  - Geometry Nodes / Store Named Attribute / Scene Time / EEVEE を使用
- 追加の Python パッケージは不要です（Blender 内蔵の `bpy` を使用）

### Blender バージョンの確認方法

```bash
/Applications/Blender.app/Contents/MacOS/Blender --version
```

スクリプトは実行時に `bpy.app.version` を読み、EEVEE 名称
（`BLENDER_EEVEE` / `BLENDER_EEVEE_NEXT`）や Geometry Nodes の
インターフェース差（3.x / 4.x）を自動で吸収します。

---

## 2. ファイル構成

| ファイル | 役割 |
| --- | --- |
| `build_output_world.py` | メイン。シーン一式を再生成し `.blend` とプレビューを保存 |
| `config.json` | 調整可能なパラメータ |
| `render_previews.py` | 保存済み `.blend` に対しプレビューだけを再描画 |
| `README_JA.md` | 本ドキュメント |
| `.gitignore` | 生成物を Git 管理から除外 |

生成物はすべて `output/` 以下に出力されます。

```
output/
├── output_world.blend      # 保存されたシーン
├── previews/               # 3カメラの静止画プレビュー
├── render/                 # ショット別の連番出力先
└── backups/                # 実行前の .blend バックアップ
```

---

## 3. 実行方法

### 3-1. ターミナルから（ヘッドレス）

```bash
# 便利なように環境変数に登録
BLENDER=/Applications/Blender.app/Contents/MacOS/Blender

# シーン構築 + .blend 保存 + プレビュー3枚
"$BLENDER" --background --python build_output_world.py
```

オプション（`--` の後ろに指定）:

```bash
# プレビュー描画を省略（構築と保存だけ・高速）
"$BLENDER" --background --python build_output_world.py -- --no-previews

# 構築後に特定ショットを最終設定で連番レンダリング（06 / 07 / 08）
"$BLENDER" --background --python build_output_world.py -- --shot 08
```

### 3-2. Blender 内 Text Editor から

1. Blender を起動
2. **Scripting** ワークスペースを開く
3. **Open** で `build_output_world.py` を開く
4. **Run Script**（▶）を実行

> `__file__` が無い環境でも、開いている `.blend` の場所または作業ディレクトリを
> 基準に `config.json` / `output/` を探します。未保存の場合はカレント
> ディレクトリが基準になるため、あらかじめ一度 `.blend` を保存しておくと確実です。

### 3-3. プレビューだけを更新

```bash
"$BLENDER" -b output/output_world.blend -P render_previews.py
```

---

## 4. 設定値（config.json）の意味

| キー | 意味 | 既定値 |
| --- | --- | --- |
| `grid_x` | グリッドの X 分割数（＝X 方向のブロック数） | 32 |
| `grid_y` | グリッドの Y 分割数（＝Y 方向のブロック数） | 32 |
| `spacing` | ブロック間隔（m）。総サイズ = (分割数-1)×spacing | 1.0 |
| `min_height` | ブロック最小高さ（端の低いブロック） | 0.4 |
| `max_height` | ブロック最大高さ（中心の山の高さ） | 9.0 |
| `noise_scale` | Noise の空間周波数（大きいほど山が細かい） | 2.2 |
| `noise_strength` | Noise の高さへの寄与（山のばらつき） | 1.0 |
| `center_peak_strength` | 中央バイアスの強さ（中心に山を集める度合い） | 1.0 |
| `build_start_frame` | ビルド開始フレーム | 1 |
| `build_end_frame` | ビルド完了フレーム | 32 |
| `red_ratio` | 赤ノードの割合（0.015 = 約1.5%） | 0.015 |
| `random_seed` | 乱数シード。**固定すると赤の位置・高さが毎回同じ** | 20260714 |
| `preview_resolution_percentage` | プレビュー解像度％（50 = 960×540） | 50 |
| `final_resolution_percentage` | 最終解像度％（100 = 1920×1080） | 100 |
| `output_format` | `PNG`（連番）または `OPEN_EXR`（連番） | "PNG" |

`grid_x` × `grid_y` が総インスタンス数です（初期値 32×32 = **1024**）。
値を増やしてもオブジェクト数は増えず、GN のインスタンスとして軽量に保たれます。

### 高さの決まり方（中心に複数の山）

```
中央バイアス(中心=1,端=0, Smooth Step) × center_peak_strength
        × Noise(複数の山) × noise_strength
        + Random × 0.12
  → 0..1 にクランプ → min_height〜max_height にマップ
```

底面は z=0 に固定され、各ブロックは **上方向にのみ**成長します。
`build_start_frame`〜`build_end_frame` の間に、中心から外側へ Smooth Step の
波が広がり、各ブロックの Z スケールが 0 から最終値へ変化します。

---

## 5. カメラとタイムライン

| フレーム | ショット | カメラ | 焦点距離 | 動き |
| --- | --- | --- | --- | --- |
| 1–32 | OUTPUT EMERGENCE | `OW_CAM_06_EMERGENCE` | 40mm | 低め中距離・わずかにドリーイン |
| 33–64 | DIVE THROUGH OUTPUT | `OW_CAM_07_DIVE` | 24mm | ブロック内部を高速移動・非衝突・強パララックス |
| 65–96 | HERO REVEAL | `OW_CAM_08_HERO` | 50mm | 上昇しながら後退・全景ヒーロー構図 |

- 全体尺 **96 フレーム / 24fps / 1920×1080**
- タイムラインマーカーでカメラを自動切替（1 回のアニメ描画で全カット切替）
- ショット単体描画は `-- --shot 06/07/08`

---

## 6. レンダー設定（プレビュー / 最終の2段階）

| 項目 | プレビュー | 最終 |
| --- | --- | --- |
| 解像度 | 960×540（`preview_resolution_percentage`） | 1920×1080（`final_resolution_percentage`） |
| サンプル | 低（16） | 高（128） |
| モーションブラー | OFF | ON |
| 被写界深度(DOF) | OFF | CAM_08 のみ ON |
| 背景 | 透過（RGBA） | 透過（RGBA） |

- レンダーエンジンは **EEVEE**（バージョンに応じ自動選択）
- 背景透過なので **After Effects** でそのまま合成できます
- PNG は 16bit RGBA 連番、OpenEXR は ZIP 圧縮 RGBA 連番

---

## 7. 安全性・再実行性

- 何度実行しても重複オブジェクトは増えません。
- 再生成対象は **`OUTPUT_WORLD` Collection** と接頭辞 **`OW_`** のデータのみ。
  **ユーザーの他 Collection・他データには一切触れません**。
- 実行前に既存 `output/output_world.blend` を
  `output/backups/` へ**コピー**してバックアップします（削除はしません）。
- スクリプトは**ファイルを削除しません**（`os.remove` / `rmtree` は未使用）。
- 可能な限り `bpy.ops` を避け、Blender Data API を使用しています
  （描画・保存など一部のみ `bpy.ops`）。

---

## 8. エラー時の確認方法

エラー時は `[OUTPUT_WORLD] ERROR:` 付きのログと traceback が表示されます。
以下を順に確認してください。

1. **実行環境**: Blender の Python から実行しているか
   （`import bpy` に失敗する場合は通常の Python で実行しています）。
2. **Blender バージョン**: `--version` で確認。4.x 推奨、3.4 未満は非対応の可能性。
3. **config.json**: JSON として妥当か、`max_height > min_height` か、
   `grid_x`/`grid_y` が 2 以上か。未知キーや値域外は警告ログに出ます。
4. **Geometry Nodes 関連のエラー**: ノード名がバージョンで変わっている場合は
   ログのノード名を確認。EEVEE 名称は自動選択されます。
5. **書き込み権限**: `output/` に書き込めるか（保存・バックアップに必要）。

ログはターミナル（ヘッドレス実行時）または Blender の
**Window > Toggle System Console**（GUI 実行時）で確認できます。

---

## 9. プレビューの作り方（まとめ）

```bash
BLENDER=/Applications/Blender.app/Contents/MacOS/Blender

# A) 構築と同時にプレビュー3枚を生成（既定）
"$BLENDER" --background --python build_output_world.py

# B) 既存 .blend からプレビューだけ再生成
"$BLENDER" -b output/output_world.blend -P render_previews.py
```

生成された静止画は `output/previews/OW_CAM_06_EMERGENCE.png` などとして
保存されます（背景透過 PNG）。
