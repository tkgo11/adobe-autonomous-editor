#!/usr/bin/env python3
"""Create compact visual/audio evidence for multimodal QC and edit review."""
from __future__ import annotations
import argparse, json, math, shutil, subprocess
from pathlib import Path

def run(cmd):
    p=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE);return p.returncode,p.stdout,p.stderr

def duration(ffprobe,media):
    c,o,e=run([ffprobe,"-v","error","-show_entries","format=duration","-of","default=nw=1:nk=1",str(media)])
    return float(o.strip()) if c==0 and o.strip() else 0.0

def main():
    ap=argparse.ArgumentParser();ap.add_argument("media");ap.add_argument("--out-dir",required=True);ap.add_argument("--frames",type=int,default=12);ns=ap.parse_args()
    ffmpeg=shutil.which("ffmpeg");ffprobe=shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:raise SystemExit("ffmpeg/ffprobe required")
    media=Path(ns.media).resolve();out=Path(ns.out_dir).resolve();out.mkdir(parents=True,exist_ok=True);d=duration(ffprobe,media);shots=[]
    n=max(1,ns.frames)
    for i in range(n):
        t=(d*(i+0.5)/n) if d else 0;f=out/f"frame-{i:03d}-{t:.2f}s.jpg";c,_,e=run([ffmpeg,"-y","-ss",f"{t:.3f}","-i",str(media),"-frames:v","1","-q:v","2",str(f)]);shots.append({"time":t,"path":str(f),"ok":c==0})
    waveform=out/"waveform.png";run([ffmpeg,"-y","-i",str(media),"-filter_complex","showwavespic=s=1600x320:split_channels=1","-frames:v","1",str(waveform)])
    contact=out/"contact-sheet.jpg"
    fps=(n/d) if d>0 else 1
    run([ffmpeg,"-y","-i",str(media),"-vf",f"fps={fps},scale=320:-1,tile=4x{math.ceil(n/4)}","-frames:v","1","-q:v","3",str(contact)])
    payload={"media":str(media),"duration":d,"frames":shots,"contact_sheet":str(contact),"waveform":str(waveform)};(out/"review-packet.json").write_text(json.dumps(payload,indent=2),encoding="utf-8");print(out/"review-packet.json")
if __name__=="__main__":main()
