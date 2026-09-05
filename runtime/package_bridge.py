#!/usr/bin/env python3
from __future__ import annotations
import argparse, shutil, zipfile
from pathlib import Path

def package(template:Path,out_dir:Path,secret:str):
    work=out_dir/"premiere-uxp"; shutil.rmtree(work,ignore_errors=True); shutil.copytree(template,work)
    cfg=work/"runtime-config.js";cfg.write_text(cfg.read_text(encoding="utf-8").replace("__AUTONOMOUS_EDITOR_SECRET__",secret),encoding="utf-8")
    ccx=out_dir/"com.autonomous-editor.bridge.ccx"
    with zipfile.ZipFile(ccx,"w",zipfile.ZIP_DEFLATED) as z:
        for f in work.rglob("*"):
            if f.is_file() and not f.name.endswith(".bak"):z.write(f,f.relative_to(work).as_posix())
    return work,ccx

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--template",required=True);ap.add_argument("--out",required=True);ap.add_argument("--secret",required=True);ns=ap.parse_args()
    work,ccx=package(Path(ns.template),Path(ns.out),ns.secret);print(ccx)
if __name__=="__main__":main()
