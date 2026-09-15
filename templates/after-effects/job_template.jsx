(function autonomousEditorJob() {
    var RESULT_PATH = "__RESULT_JSON_PATH__";

    // ExtendScript is ES3; JSON.stringify is unavailable on some AE versions.
    function esc(s){return String(s).replace(/\\/g,"\\\\").replace(/\"/g,'\\"').replace(/[\x00-\x1f]/g,function(c){var n=c.charCodeAt(0);return n===10?"\\n":n===13?"\\r":n===9?"\\t":"\\u"+("0000"+n.toString(16)).slice(-4);}).replace(/\u2028/g,"\\u2028").replace(/\u2029/g,"\\u2029");}
    function stringify(x){
        if(x===null)return "null";
        var t=typeof x;
        if(t==="string")return '"'+esc(x)+'"';
        if(t==="number"||t==="boolean")return String(x);
        if(x instanceof Array){var a=[];for(var i=0;i<x.length;i++)a.push(stringify(x[i]));return "["+a.join(",")+"]";}
        var p=[];for(var k in x){if(x.hasOwnProperty(k))p.push('"'+esc(k)+'":'+stringify(x[k]));}return "{"+p.join(",")+"}";
    }

    function writeResult(obj) {
        var f = new File(RESULT_PATH);
        f.encoding = "UTF-8";
        f.open("w");
        f.write(stringify(obj));
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
