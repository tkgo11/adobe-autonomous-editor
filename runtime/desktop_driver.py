#!/usr/bin/env python3
"""Deterministic desktop fallback for Premiere/After Effects.

The agent should prefer Adobe APIs. This driver is for gaps. It exposes screenshots and
accessibility trees so a vision-capable parent agent can reason about the current UI,
then issue narrowly scoped, verifiable actions.
"""
from __future__ import annotations
import argparse, ctypes, json, platform, re, shutil, subprocess, time
from pathlib import Path


def _imports():
    if platform.system() != "Windows":
        raise RuntimeError("Windows UIA backend requested on a non-Windows platform")
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


def _as_string(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _osascript(source):
    executable = shutil.which("osascript")
    if not executable:
        raise RuntimeError("osascript is unavailable")
    run = subprocess.run([executable, "-e", source], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    if run.returncode:
        raise RuntimeError(run.stderr.strip() or f"osascript failed with {run.returncode}")
    return run.stdout.strip()


def _mac_windows():
    source = '''
set rows to {}
tell application "System Events"
  repeat with p in (application processes whose background only is false)
    set pn to name of p
    repeat with w in windows of p
      try
        set windowNumber to ""
        try
          set windowNumber to (value of attribute "AXWindowNumber" of w) as text
        end try
        set end of rows to pn & tab & (name of w) & tab & windowNumber
      end try
    end repeat
  end repeat
end tell
set AppleScript's text item delimiters to linefeed
return rows as text
'''
    rows = []
    for line in _osascript(source).splitlines():
        parts = line.split("\t", 2)
        if len(parts) >= 2:
            process, title = parts[:2]
            window_id = parts[2].strip() if len(parts) == 3 else ""
            rows.append({"process": process, "title": title, "window_id": window_id or None})
    return rows


def _mac_find_window(title_re):
    pattern = re.compile(title_re)
    for row in _mac_windows():
        if pattern.search(row["title"]):
            return row
    raise RuntimeError(f"Window not found: {title_re}")


def _mac_focus(window):
    process = _as_string(window["process"])
    title = _as_string(window["title"])
    _osascript(f'''
tell application "System Events" to tell process "{process}"
  set frontmost to true
  set targetWindow to first window whose name is "{title}"
  perform action "AXRaise" of targetWindow
end tell
''')


def _mac_click_control(window, step, set_text=None):
    process = _as_string(window["process"])
    window_title = _as_string(window["title"])
    role = str(step.get("control_type") or "button").lower()
    ax_role = {
        "button": "AXButton", "axbutton": "AXButton", "menuitem": "AXMenuItem",
        "axmenuitem": "AXMenuItem", "edit": "AXTextField", "textfield": "AXTextField",
        "axtextfield": "AXTextField", "checkbox": "AXCheckBox", "axcheckbox": "AXCheckBox",
    }.get(role, "")
    title_value = step.get("title") or step.get("name")
    if not title_value and step.get("title_re"):
        try:
            pattern = re.compile(str(step["title_re"]))
        except re.error as exc:
            raise RuntimeError(f"Invalid macOS accessibility title_re: {exc}") from exc
        matches = [
            row["name"] for row in _mac_dump_tree(window, int(step.get("maxChildren", 1500)))
            if row.get("name") and pattern.search(row["name"])
            and (not ax_role or row.get("role") == ax_role)
        ]
        if not matches:
            raise RuntimeError(f"Accessibility element not found for title_re: {step['title_re']}")
        title_value = matches[0]
    title = _as_string(title_value or "")
    if not title:
        raise RuntimeError("macOS accessibility action requires title, name, or title_re")
    action = (
        f'set value of hit to "{_as_string(set_text)}"'
        if set_text is not None else
        'perform action "AXPress" of hit'
    )
    source = f'''
on findElement(rootElement, targetName, targetRole)
  tell application "System Events"
    try
      if (name of rootElement as text) is targetName then
        if targetRole is "" or (role of rootElement as text) is targetRole then return rootElement
      end if
    end try
    try
      repeat with childElement in UI elements of rootElement
        set hit to my findElement(childElement, targetName, targetRole)
        if hit is not missing value then return hit
      end repeat
    end try
  end tell
  return missing value
end findElement
tell application "System Events"
  tell process "{process}"
    set frontmost to true
    set targetWindow to first window whose name is "{window_title}"
    set hit to my findElement(targetWindow, "{title}", "{ax_role}")
    if hit is missing value then error "Accessibility element not found: {title}"
    {action}
  end tell
end tell
'''
    _osascript(source)


def _mac_key(key, modifiers=None):
    modifiers = modifiers or []
    modifier_names = {
        "ctrl": "control down", "control": "control down", "alt": "option down",
        "option": "option down", "shift": "shift down", "cmd": "command down",
        "command": "command down", "win": "command down",
    }
    using = [modifier_names[item.lower()] for item in modifiers if item.lower() in modifier_names]
    suffix = f" using {{{', '.join(using)}}}" if using else ""
    key_codes = {
        "enter": 36, "return": 36, "escape": 53, "esc": 53, "tab": 48,
        "space": 49, "delete": 51, "backspace": 51, "left": 123,
        "right": 124, "down": 125, "up": 126,
    }
    lowered = key.lower().strip("{}")
    command = f"key code {key_codes[lowered]}{suffix}" if lowered in key_codes else f'keystroke "{_as_string(key)}"{suffix}'
    _osascript(f'tell application "System Events" to {command}')


def _mac_mouse(x, y, click=False):
    app_services = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
    core_foundation = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    class Point(ctypes.Structure):
        _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]
    app_services.CGEventCreateMouseEvent.restype = ctypes.c_void_p
    app_services.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, Point, ctypes.c_uint32]
    app_services.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    core_foundation.CFRelease.argtypes = [ctypes.c_void_p]
    for event_type in ([5] if not click else [5, 1, 2]):
        event = app_services.CGEventCreateMouseEvent(None, event_type, Point(float(x), float(y)), 0)
        if not event:
            raise RuntimeError("Could not create macOS mouse event")
        app_services.CGEventPost(0, event)
        core_foundation.CFRelease(event)


def _mac_dump_tree(window, limit=1500):
    process = _as_string(window["process"])
    title = _as_string(window["title"])
    source = f'''
property outputRows : {{}}
property rowLimit : {max(0, int(limit))}

on walkElement(e)
  if (count of my outputRows) is greater than or equal to my rowLimit then return
  tell application "System Events"
    try
      set end of my outputRows to (role of e as text) & tab & (name of e as text) & tab & (description of e as text)
    end try
    if (count of my outputRows) is greater than or equal to my rowLimit then return
    try
      set childElements to UI elements of e
    on error
      set childElements to {{}}
    end try
  end tell
  repeat with childElement in childElements
    my walkElement(childElement)
    if (count of my outputRows) is greater than or equal to my rowLimit then exit repeat
  end repeat
end walkElement

set outputRows to {{}}
tell application "System Events" to tell process "{process}"
  set targetWindow to first window whose name is "{title}"
  my walkElement(targetWindow)
end tell
set AppleScript's text item delimiters to linefeed
return outputRows as text
'''
    return [{"role": parts[0], "name": parts[1], "description": parts[2]} for line in _osascript(source).splitlines() if len(parts := line.split("\t", 2)) == 3]


def _mac_menu_select(window, path):
    parts = [part.strip() for part in re.split(r"->|>", path) if part.strip()]
    if len(parts) < 2:
        raise RuntimeError("macOS menu path must contain at least Menu -> Item")
    process = _as_string(window["process"])
    top = _as_string(parts[0])
    menu_ref = f'menu "{top}" of menu bar item "{top}" of menu bar 1'
    for intermediate in parts[1:-1]:
        item = _as_string(intermediate)
        menu_ref = f'menu "{item}" of menu item "{item}" of {menu_ref}'
    final = _as_string(parts[-1])
    _osascript(f'''
tell application "System Events" to tell process "{process}"
  set frontmost to true
  click menu bar item "{top}" of menu bar 1
  click menu item "{final}" of {menu_ref}
end tell
''')


def _run_steps_macos(steps):
    results=[]; current=None
    for i,s in enumerate(steps):
        op=s["op"]
        try:
            if op=="wait": time.sleep(float(s.get("seconds",1)))
            elif op in {"focus_window","wait_window"}:
                deadline=time.time()+float(s.get("timeout",30)); current=None
                while time.time()<deadline:
                    try: current=_mac_find_window(s["title_re"]); break
                    except Exception: time.sleep(.25)
                if current is None: raise RuntimeError("window wait timed out")
                _mac_focus(current)
            elif op=="uia_click":
                if current is None: current=_mac_find_window(s["title_re"])
                _mac_click_control(current,s)
            elif op=="uia_set_text":
                if current is None: current=_mac_find_window(s["title_re"])
                _mac_click_control(current,s,s.get("text",""))
            elif op in {"send_keys","typewrite"}: _mac_key(s.get("keys",s.get("text","")))
            elif op=="hotkey": _mac_key(s["keys"][-1],s["keys"][:-1])
            elif op=="press":
                for _ in range(int(s.get("presses",1))): _mac_key(s["key"]);time.sleep(float(s.get("interval",.05)))
            elif op in {"click","move"}:
                count=int(s.get("clicks",1)) if op=="click" else 1
                for _ in range(count): _mac_mouse(int(s["x"]),int(s["y"]),op=="click");time.sleep(float(s.get("interval",.1)))
            elif op=="screenshot":
                path=Path(s["path"]).resolve();path.parent.mkdir(parents=True,exist_ok=True)
                capture=shutil.which("screencapture") or "/usr/sbin/screencapture"
                command=[capture,"-x"]
                window_only = s.get("windowOnly", current is not None)
                if window_only:
                    if current is None:
                        raise RuntimeError("windowOnly screenshot requires a focused or waited-for window")
                    if not current.get("window_id"):
                        raise RuntimeError("selected macOS window does not expose AXWindowNumber")
                    command.extend(["-l",str(current["window_id"])])
                command.append(str(path))
                run=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=30)
                if run.returncode: raise RuntimeError(run.stderr.strip())
                results.append({"index":i,"op":op,"ok":True,"path":str(path)});continue
            elif op=="dump_tree":
                if current is None: current=_mac_find_window(s["title_re"])
                data=_mac_dump_tree(current,int(s.get("maxChildren",1500)))
                if s.get("path"):
                    p=Path(s["path"]).resolve();p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")
                results.append({"index":i,"op":op,"ok":True,"tree":data if not s.get("path") else None,"path":s.get("path")});continue
            elif op=="menu_select":
                if current is None: current=_mac_find_window(s["title_re"])
                _mac_menu_select(current,s["path"])
            else: raise RuntimeError(f"Unsupported macOS desktop op: {op}")
            results.append({"index":i,"op":op,"ok":True})
        except Exception as exc:
            results.append({"index":i,"op":op,"ok":False,"error":str(exc)})
            if not s.get("continueOnError",False): break
    return results


def run_steps(steps):
    if platform.system() == "Darwin":
        return _run_steps_macos(steps)
    if platform.system() != "Windows":
        return [{"index": 0, "op": "platform", "ok": False, "error": "Adobe desktop fallback is supported on Windows and macOS; Linux uses Crafting Apps only"}]
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
