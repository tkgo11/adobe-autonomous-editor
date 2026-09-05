#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, mimetypes, shutil, subprocess
from pathlib import Path

def run(cmd):
    p=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    return p.returncode,p.stdout,p.stderr

def fingerprint(path:Path,chunk=2*1024*1024):
    h=hashlib.sha256();size=path.stat().st_size
    with path.open("rb") as f:
        h.update(f.read(chunk))
        if size>chunk:
            f.seek(max(0,size-chunk));h.update(f.read(chunk))
    h.update(str(size).encode());return "sha256-head-tail-size:"+h.hexdigest()

def probe(ffprobe,path):
    if not ffprobe:return None
    code,out,err=run([ffprobe,"-v","error","-show_format","-show_streams","-of","json",str(path)])
    if code:return {"ok":False,"error":err[-4000:]}
    try:return {"ok":True,"data":json.loads(out)}
    except Exception as e:return {"ok":False,"error":str(e)}

def kind(path):
    ext=path.suffix.lower()
    if ext in {".prproj",".aep",".aepx"}:return "project"
    if ext in {".srt",".vtt",".ass",".ssa"}:return "subtitle"
    if ext in {".mogrt"}:return "mogrt"
    if ext in {".cube",".look"}:return "lut"
    if ext in {".ttf",".otf"}:return "font"
    mime=mimetypes.guess_type(path.name)[0] or ""
    if mime.startswith("video/"):return "video"
    if mime.startswith("audio/"):return "audio"
    if mime.startswith("image/"):return "image"
    return "asset"

def main():
    ap=argparse.ArgumentParser();ap.add_argument("paths",nargs="+");ap.add_argument("--out",required=True);ns=ap.parse_args()
    ffprobe=shutil.which("ffprobe");rows=[]
    for raw in ns.paths:
        p=Path(raw).expanduser().resolve()
        if p.is_dir(): files=[x for x in p.rglob("*") if x.is_file()]
        else: files=[p]
        for x in files:
            row={"path":str(x),"exists":x.exists(),"kind":kind(x)}
            if x.exists():
                st=x.stat();row.update({"name":x.name,"extension":x.suffix.lower(),"size":st.st_size,"mtime":st.st_mtime,"fingerprint":fingerprint(x)})
                if row["kind"] in {"video","audio","image"}:row["probe"]=probe(ffprobe,x)
            rows.append(row)
    out=Path(ns.out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps({"sources":rows},indent=2,ensure_ascii=False),encoding="utf-8");print(out)
if __name__=="__main__":main()
