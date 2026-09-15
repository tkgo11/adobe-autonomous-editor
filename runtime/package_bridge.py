#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, shutil, zipfile
from pathlib import Path

def _js_string_literal(s: str) -> str:
    # The secret is embedded in a JS string literal; JSON-escape it so quotes or
    # control characters in a caller-supplied secret cannot break out of the
    # string. U+2028/U+2029 are ES3 line terminators and must stay escaped.
    return json.dumps(str(s), ensure_ascii=False).replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")

def package(template:Path,out_dir:Path,secret:str):
    work=out_dir/"premiere-uxp"; shutil.rmtree(work,ignore_errors=True); shutil.copytree(template,work)
    cfg=work/"runtime-config.js";text=cfg.read_text(encoding="utf-8")
    literal=_js_string_literal(secret)
    if '"__AUTONOMOUS_EDITOR_SECRET__"' in text:
        text=text.replace('"__AUTONOMOUS_EDITOR_SECRET__"',literal)
    else:
        text=text.replace("__AUTONOMOUS_EDITOR_SECRET__",literal[1:-1])
    cfg.write_text(text,encoding="utf-8")
    ccx=out_dir/"com.autonomous-editor.bridge.ccx"
    with zipfile.ZipFile(ccx,"w",zipfile.ZIP_DEFLATED) as z:
        for f in sorted(work.rglob("*")):
            if f.is_file() and not f.name.endswith(".bak"):z.write(f,f.relative_to(work).as_posix())
    return work,ccx

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--template",required=True);ap.add_argument("--out",required=True);ap.add_argument("--secret",required=True);ns=ap.parse_args()
    work,ccx=package(Path(ns.template),Path(ns.out),ns.secret);print(ccx)
if __name__=="__main__":main()
