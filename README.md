# Blender OUTPUT World

BlenderによるOUTPUTフィールド自動生成プロジェクト

## 概要 / Overview

Blender の Python API (`bpy`) を使って、地形（OUTPUT フィールド）・散布オブジェクト・
ライティング・カメラを手続き的に生成し、1 枚の画像としてレンダリング出力するツールです。

A headless, procedural generator that builds a 3D "OUTPUT field" world in
Blender — displaced terrain, scattered primitives, sun lighting, and a
framed camera — then renders it to an image.

## 実行方法 / Usage

Blender をインストールした状態で、ヘッドレス実行します:

```bash
blender --background --python generate_world.py
```

オプションは `--` の後に指定します:

```bash
blender --background --python generate_world.py -- --samples 128 --scatter 80 --out output --name my_world
```

| オプション | 説明 | 既定値 |
| --- | --- | --- |
| `--samples` | レンダリングサンプル数 | 64 |
| `--scatter` | 散布オブジェクト数 | 60 |
| `--out` | 出力ディレクトリ | `output` |
| `--name` | 出力ファイル名（拡張子なし） | `output_world` |

レンダリング結果は `output/output_world.png` に書き出されます。

## 構成 / Structure

```
generate_world.py        # エントリポイント (Blender から実行)
blender_world/
├── __init__.py          # build_world() パイプライン
├── config.py            # 全パラメータ (dataclass)
├── scene.py             # シーン初期化
├── terrain.py           # 地形 (OUTPUT フィールド) 生成
├── objects.py           # オブジェクト散布
├── lighting.py          # 太陽光・ワールド背景
├── camera.py            # カメラ配置
└── render.py            # レンダリング設定・出力
```

## 開発 / Development

`bpy` は Blender 内蔵の Python から提供されるため、実行時に別途インストールは不要です。
エディタ補完・型チェック用のスタブのみ任意で導入できます:

```bash
pip install -r requirements-dev.txt
```

