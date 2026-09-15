#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, mimetypes, os, shutil, subprocess
from pathlib import Path

def run(cmd, timeout=None):
    try:
        p=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124,"","timed out"
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
    code,out,err=run([ffprobe,"-v","error","-show_format","-show_streams","-of","json",str(path)],timeout=120)
    if code:return {"ok":False,"error":err[-4000:]}
    try:return {"ok":True,"data":json.loads(out)}
    except Exception as e:return {"ok":False,"error":str(e)}

# mimetypes is platform/registry dependent and misses professional camera and
# post-production formats (.mxf, .mts/.m2ts, .r3d, .braw, .crm, .vob, .ts, ...),
# so common AV extensions are classified explicitly before falling back to MIME.
VIDEO_EXT={".mp4",".m4v",".mov",".qt",".mxf",".mts",".m2ts",".ts",".mkv",".webm",".avi",
    ".wmv",".asf",".flv",".f4v",".vob",".mpg",".mpeg",".m2v",".mpe",".mpv",".3gp",".3g2",
    ".r3d",".braw",".crm",".ari",".arx",".divx",".ogv",".m2p",".m4s",".insv",".mod",".tod"}
AUDIO_EXT={".wav",".aif",".aiff",".aifc",".mp3",".m4a",".aac",".flac",".ogg",".opus",
    ".wma",".alac",".caf",".bwf",".mid",".midi"}
IMAGE_EXT={".png",".jpg",".jpeg",".jpe",".tif",".tiff",".bmp",".gif",".webp",".heic",
    ".heif",".exr",".dpx",".cin",".svg",".psd",".ai",".eps",".indd",".ico",".avif",".jxl"}
PROJECT_EXT={".prproj",".aep",".aepx",".prfpset"}
SUBTITLE_EXT={".srt",".vtt",".ass",".ssa",".sub",".sbv",".stl"}
KIND_BY_EXT={}
for _e in VIDEO_EXT: KIND_BY_EXT[_e]="video"
for _e in AUDIO_EXT: KIND_BY_EXT[_e]="audio"
for _e in IMAGE_EXT: KIND_BY_EXT[_e]="image"
for _e in PROJECT_EXT: KIND_BY_EXT[_e]="project"
for _e in SUBTITLE_EXT: KIND_BY_EXT[_e]="subtitle"
for _e,k in {".mogrt":"mogrt",".cube":"lut",".look":"lut",".ttf":"font",".otf":"font",
             ".prproj":"project",".aep":"project",".aepx":"project"}.items():
    KIND_BY_EXT[_e]=k

def kind(path):
    ext=path.suffix.lower()
    if ext in KIND_BY_EXT:return KIND_BY_EXT[ext]
    mime=mimetypes.guess_type(path.name)[0] or ""
    if mime.startswith("video/"):return "video"
    if mime.startswith("audio/"):return "audio"
    if mime.startswith("image/"):return "image"
    return "asset"

def iter_files(root:Path):
    """Depth-first file listing immune to symlink cycles (each real dir visited once)."""
    seen=set();stack=[root]
    while stack:
        d=stack.pop()
        try:
            real=d.resolve()
            if real in seen:continue
            seen.add(real)
            entries=sorted(os.scandir(d),key=lambda e:e.name)
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_dir():stack.append(Path(e.path))
                elif e.is_file():yield Path(e.path)
            except OSError:
                continue

def main():
    ap=argparse.ArgumentParser();ap.add_argument("paths",nargs="+");ap.add_argument("--out",required=True);ns=ap.parse_args()
    ffprobe=shutil.which("ffprobe");rows=[]
    for raw in ns.paths:
        p=Path(raw).expanduser().resolve()
        if p.is_dir(): files=sorted(iter_files(p),key=lambda x:str(x))
        else: files=[p]
        for x in files:
            row={"path":str(x),"exists":x.exists(),"kind":kind(x)}
            if x.exists():
                try:
                    st=x.stat();row.update({"name":x.name,"extension":x.suffix.lower(),"size":st.st_size,"mtime":st.st_mtime,"fingerprint":fingerprint(x)})
                    if row["kind"] in {"video","audio","image"}:row["probe"]=probe(ffprobe,x)
                except OSError as e:
                    row["error"]=str(e)
            rows.append(row)
    out=Path(ns.out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps({"sources":rows},indent=2,ensure_ascii=False),encoding="utf-8");print(out)
if __name__=="__main__":main()
