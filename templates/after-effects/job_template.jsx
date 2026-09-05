(function autonomousEditorJob() {
    var RESULT_PATH = "__RESULT_JSON_PATH__";

    function writeResult(obj) {
        var f = new File(RESULT_PATH);
        f.encoding = "UTF-8";
        f.open("w");
        f.write(JSON.stringify(obj));
        f.close();
    }

    app.beginUndoGroup("Autonomous Editor Job");
    try {
        // Replace this block with generated, job-specific AE operations.
        // Prefer explicit DOM calls over eval/dynamic code execution.

        app.endUndoGroup();
        writeResult({ ok: true, finishedAt: (new Date()).toISOString() });
    } catch (e) {
        try { app.endUndoGroup(); } catch (_) {}
        writeResult({
            ok: false,
            name: e.name,
            message: e.message,
            line: e.line,
            source: e.source
        });
        throw e;
    }
})();
