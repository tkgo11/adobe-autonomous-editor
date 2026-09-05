#!/usr/bin/env python3
"""Deterministic Windows desktop fallback for Premiere/After Effects.

The agent should prefer Adobe APIs. This driver is for gaps. It exposes screenshots and
accessibility trees so a vision-capable parent agent can reason about the current UI,
then issue narrowly scoped, verifiable actions.
"""
from __future__ import annotations
import argparse, json, platform, time
from pathlib import Path


def _imports():
    if platform.system() != "Windows":
        raise RuntimeError("desktop_driver currently supports Windows only")
    from pywinauto import Desktop, Application
    from pywinauto.keyboard import send_keys
    import pyautogui
    return Desktop, Application, send_keys, pyautogui


def find_window(title_re: str):
    Desktop, _, _, _ = _imports()
    wins = Desktop(backend="uia").windows(title_re=title_re, visible_only=True)
    if not wins:
        raise RuntimeError(f"Window not found: {title_re}")
    return wins[0]


def dump_tree(win, max_depth=5, max_children=1500):
    out=[]
    def rec(ctrl, depth):
        if len(out)>=max_children or depth>max_depth: return
        try:
            info=ctrl.element_info
            out.append({"depth":depth,"name":info.name,"control_type":info.control_type,"automation_id":info.automation_id,"class_name":info.class_name,"rectangle":str(info.rectangle),"enabled":ctrl.is_enabled(),"visible":ctrl.is_visible()})
        except Exception: return
        try:
            for ch in ctrl.children(): rec(ch, depth+1)
        except Exception: pass
    rec(win,0); return out


def run_steps(steps):
    Desktop, Application, send_keys, pyautogui = _imports()
    results=[]
    current=None
    for i,s in enumerate(steps):
        op=s["op"]
        try:
            if op=="wait": time.sleep(float(s.get("seconds",1)))
            elif op=="focus_window": current=find_window(s["title_re"]); current.set_focus()
            elif op=="wait_window":
                deadline=time.time()+float(s.get("timeout",30)); current=None
                while time.time()<deadline:
                    try: current=find_window(s["title_re"]); break
                    except Exception: time.sleep(.25)
                if current is None: raise RuntimeError("window wait timed out")
            elif op=="uia_click":
                if current is None: current=find_window(s["title_re"])
                kwargs={k:s[k] for k in ("title","title_re","auto_id","control_type") if k in s}
                c=current.child_window(**kwargs); c.wait("exists enabled visible ready",timeout=float(s.get("timeout",10))); c.click_input()
            elif op=="uia_set_text":
                if current is None: current=find_window(s["title_re"])
                kwargs={k:s[k] for k in ("title","title_re","auto_id","control_type") if k in s}
                c=current.child_window(**kwargs); c.wait("exists enabled visible ready",timeout=float(s.get("timeout",10))); c.set_edit_text(s.get("text",""))
            elif op=="send_keys": send_keys(s["keys"],pause=float(s.get("pause",0.03)),with_spaces=True)
            elif op=="hotkey": pyautogui.hotkey(*s["keys"])
            elif op=="press": pyautogui.press(s["key"], presses=int(s.get("presses",1)), interval=float(s.get("interval",0.05)))
            elif op=="typewrite": pyautogui.write(s.get("text",""), interval=float(s.get("interval",0.01)))
            elif op=="click": pyautogui.click(int(s["x"]),int(s["y"]),clicks=int(s.get("clicks",1)),interval=float(s.get("interval",0.1)))
            elif op=="move": pyautogui.moveTo(int(s["x"]),int(s["y"]),duration=float(s.get("duration",0.2)))
            elif op=="screenshot":
                path=Path(s["path"]).resolve(); path.parent.mkdir(parents=True,exist_ok=True)
                if current is not None and s.get("windowOnly",True): current.capture_as_image().save(path)
                else: pyautogui.screenshot().save(path)
                results.append({"index":i,"op":op,"ok":True,"path":str(path)}); continue
            elif op=="dump_tree":
                if current is None: current=find_window(s["title_re"])
                data=dump_tree(current,int(s.get("maxDepth",5)),int(s.get("maxChildren",1500)))
                if s.get("path"):
                    p=Path(s["path"]).resolve();p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")
                results.append({"index":i,"op":op,"ok":True,"tree":data if not s.get("path") else None,"path":s.get("path")});continue
            elif op=="menu_select":
                title_re=s["title_re"]; app=Application(backend="win32").connect(title_re=title_re); w=app.window(title_re=title_re); w.set_focus(); w.menu_select(s["path"])
            else: raise RuntimeError(f"Unsupported desktop op: {op}")
            results.append({"index":i,"op":op,"ok":True})
        except Exception as exc:
            results.append({"index":i,"op":op,"ok":False,"error":str(exc)})
            if not s.get("continueOnError",False): break
    return results


def main():
    ap=argparse.ArgumentParser();ap.add_argument("plan");ap.add_argument("--out")
    ns=ap.parse_args(); plan=json.loads(Path(ns.plan).read_text(encoding="utf-8")); results=run_steps(plan["steps"] if isinstance(plan,dict) else plan)
    payload={"ok":all(x.get("ok") for x in results),"results":results}
    if ns.out: Path(ns.out).write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps(payload,indent=2,ensure_ascii=False)); raise SystemExit(0 if payload["ok"] else 2)

if __name__=="__main__": main()
