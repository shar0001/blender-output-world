/*
 * import_output_world.jsx
 *
 * render_final.py で書き出した OUTPUT WORLD の連番（01〜09）を
 * After Effects に読み込み、11 秒（264 フレーム / 24fps）のコンポに並べる。
 *
 * 使い方:
 *   1. After Effects で「新規プロジェクト」を作る（既存の作品プロジェクトでは実行しない）
 *   2. ファイル > スクリプト > スクリプトファイルを実行… でこのファイルを選ぶ
 *
 * 安全のため:
 *   * 保護対象のマスター AEP が開いている場合は何もせずに終了する。
 *   * プロジェクトに既にアイテムがある場合は、続行してよいか確認する。
 *   * AEP の保存・クローズ・新規作成は一切しない（保存は手動で）。
 *   * すべて 1 つの取り消し（Undo）グループにまとめる。
 */
(function () {
    var MASTER_AEP = "/Users/shar/Documents/AE練習書き出し/イラストアニメーション_1.aep";
    var COMP_NAME = "OW_CLIMAX_01_09";
    var FOLDER_NAME = "OW_OUTPUT_WORLD";
    var FPS = 24;
    var TOTAL_FRAMES = 264;
    var WIDTH = 1920;
    var HEIGHT = 1080;
    var BG_IVORY = [244 / 255, 238 / 255, 230 / 255];  // #F4EEE6

    // [ショット名, 通しの開始フレーム, 終了フレーム]（build_output_world.py の SHOT_TABLE と同じ）
    var SHOTS = [
        ["01_CONNECT", 1, 24],
        ["02_COLLAPSE", 25, 48],
        ["03_SYNC", 49, 72],
        ["04_IGNITION", 73, 96],
        ["05_RELEASE", 97, 120],
        ["06_EMERGENCE", 121, 152],
        ["07_DIVE", 153, 184],
        ["08_HERO", 185, 216],
        ["09_FINISH", 217, 264]
    ];

    function norm(p) {
        return decodeURI(String(p)).replace(/\\/g, "/");
    }

    // ---- 安全チェック -------------------------------------------------
    if (!app.project) {
        alert("プロジェクトが開いていません。新規プロジェクトを作ってから実行してください。");
        return;
    }
    if (app.project.file !== null) {
        var cur = norm(app.project.file.fsName);
        if (cur === norm(MASTER_AEP) || app.project.file.name === File(MASTER_AEP).name) {
            alert("マスター AEP が開いています。何も変更せずに終了します。\n\n" + cur +
                  "\n\n新規プロジェクトで実行してください。");
            return;
        }
    }
    if (app.project.numItems > 0) {
        if (!confirm("このプロジェクトには既に " + app.project.numItems + " 個のアイテムがあります。\n" +
                     "新規プロジェクトでの実行をおすすめします。\n\nこのまま追加しますか？")) {
            return;
        }
    }

    // ---- 連番フォルダを探す -----------------------------------------
    var renderDir = null;
    try {
        var guess = new Folder(File($.fileName).parent.parent.fsName + "/output/render");
        if (guess.exists) { renderDir = guess; }
    } catch (e) { /* 手動選択へ */ }
    if (renderDir === null) {
        renderDir = Folder.selectDialog("output/render フォルダを選んでください（01_CONNECT〜09_FINISH が入っている場所）。まだ書き出していない場合はキャンセル");
        if (renderDir === null) { return; }
    }

    function firstFrameFile(label) {
        var dir = new Folder(renderDir.fsName + "/" + label);
        if (!dir.exists) { return null; }
        var files = dir.getFiles(function (f) {
            return (f instanceof File) && /_\d{4}\.(png|exr)$/i.test(f.name) && f.name.indexOf(label + "_") === 0;
        });
        if (files.length === 0) { return null; }
        files.sort(function (a, b) { return a.name < b.name ? -1 : (a.name > b.name ? 1 : 0); });
        return { file: files[0], count: files.length };
    }

    // ---- 連番が1本も無ければ、何も作らずに終了 -----------------------
    var available = 0;
    for (var k = 0; k < SHOTS.length; k++) {
        if (firstFrameFile(SHOTS[k][0]) !== null) { available++; }
    }
    if (available === 0) {
        alert("連番が見つかりませんでした。何も変更していません。\n\n選んだフォルダ:\n" + renderDir.fsName +
              "\n\n先に Blender で render_final.py を実行して、\n" +
              "output/render/01_CONNECT 〜 09_FINISH を書き出してください。\n" +
              "そのあと output/render フォルダを選び直してください。");
        return;
    }

    // ---- 読み込みとコンポ作成 ---------------------------------------
    app.beginUndoGroup("OUTPUT WORLD 読み込み");
    var report = [];
    var missing = [];
    try {
        var folder = app.project.items.addFolder(FOLDER_NAME);
        var comp = app.project.items.addComp(COMP_NAME, WIDTH, HEIGHT, 1.0, TOTAL_FRAMES / FPS, FPS);
        comp.parentFolder = folder;
        comp.bgColor = BG_IVORY;

        var bg = comp.layers.addSolid(BG_IVORY, "OW_BG_IVORY", WIDTH, HEIGHT, 1.0, TOTAL_FRAMES / FPS);
        bg.moveToEnd();
        try { bg.source.parentFolder = folder; } catch (e1) { /* ソリッドフォルダのまま */ }

        for (var i = 0; i < SHOTS.length; i++) {
            var label = SHOTS[i][0], start = SHOTS[i][1], end = SHOTS[i][2];
            var found = firstFrameFile(label);
            if (found === null) {
                missing.push(label);
                continue;
            }
            var io = new ImportOptions(found.file);
            io.sequence = true;
            io.forceAlphabetical = false;
            var item = app.project.importFile(io);
            item.parentFolder = folder;
            item.mainSource.conformFrameRate = FPS;
            try { item.mainSource.alphaMode = AlphaMode.STRAIGHT; } catch (e2) { /* 形式により不要 */ }

            var layer = comp.layers.add(item);
            layer.startTime = (start - 1) / FPS;   // 通しのフレーム番号に合わせて配置
            layer.name = label;
            try {
                comp.markerProperty.setValueAtTime((start - 1) / FPS, new MarkerValue(label));
            } catch (e3) { /* 古い AE ではマーカー省略 */ }
            var expect = end - start + 1;
            report.push(label + " : " + found.count + " / " + expect + " 枚" +
                        (found.count === expect ? "" : "  ← 枚数が足りません"));
        }
        comp.openInViewer();
    } catch (err) {
        alert("読み込み中にエラーが発生しました:\n" + err.toString() +
              (err.line ? "\n(行 " + err.line + ")" : ""));
    } finally {
        app.endUndoGroup();
    }

    alert("OUTPUT WORLD を読み込みました（保存はしていません）\n\n" +
          "コンポ: " + COMP_NAME + "（" + WIDTH + "x" + HEIGHT + " / " + FPS + "fps / " + TOTAL_FRAMES + "F）\n" +
          "フォルダ: " + renderDir.fsName + "\n\n" +
          report.join("\n") +
          (missing.length ? "\n\n見つからなかったショット: " + missing.join(", ") : ""));
})();
