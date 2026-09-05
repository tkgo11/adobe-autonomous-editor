#!/usr/bin/env python3
"""Compile explicit After Effects actions to ExtendScript and optionally dispatch them.

This is intentionally an action DSL, not an arbitrary-eval endpoint. For an operation
not expressible here, the parent skill may generate a reviewed one-off JSX or use the
UI fallback, then verify the rendered result.
"""
from __future__ import annotations
import argparse, json, os, subprocess, time, uuid
from pathlib import Path

JS_RUNTIME = r'''
(function () {
  var PAYLOAD = __PAYLOAD__;
  var RESULT_FILE = __RESULT_FILE__;
  var result = {ok:true, actions:[], error:null};

  function esc(s){return String(s).replace(/\\/g,"\\\\").replace(/\"/g,'\\"').replace(/\r/g,"\\r").replace(/\n/g,"\\n");}
  function stringify(x){
    if(x===null) return "null";
    var t=typeof x;
    if(t==="string") return '"'+esc(x)+'"';
    if(t==="number"||t==="boolean") return String(x);
    if(x instanceof Array){var a=[];for(var i=0;i<x.length;i++)a.push(stringify(x[i]));return "["+a.join(",")+"]";}
    var p=[];for(var k in x){if(x.hasOwnProperty(k))p.push('"'+esc(k)+'":'+stringify(x[k]));}return "{"+p.join(",")+"}";
  }
  function writeResult(){var f=new File(RESULT_FILE);f.encoding="UTF-8";f.open("w");f.write(stringify(result));f.close();}
  function comp(name){for(var i=1;i<=app.project.numItems;i++){var x=app.project.item(i);if(x instanceof CompItem && x.name===name)return x;}throw new Error("Comp not found: "+name);}
  function item(name){for(var i=1;i<=app.project.numItems;i++){var x=app.project.item(i);if(x.name===name)return x;}throw new Error("Project item not found: "+name);}
  function layer(c, spec){if(spec.index)return c.layer(Number(spec.index));if(spec.name)return c.layer(spec.name);throw new Error("Layer index/name required");}
  function prop(root,path){var p=root;for(var i=0;i<path.length;i++){p=p.property(path[i]);if(!p)throw new Error("Property not found: "+path.slice(0,i+1).join(" / "));}return p;}
  function arr(v){return v instanceof Array?v:[v];}
  function shapeFrom(a){
    var sh=new Shape(); sh.vertices=a.vertices||[]; sh.inTangents=a.inTangents||[]; sh.outTangents=a.outTangents||[]; sh.closed=a.closed!==false; return sh;
  }
  function targetMask(l,a){
    var masks=l.property("ADBE Mask Parade"); var m=a.maskIndex?masks.property(Number(a.maskIndex)):masks.property(a.maskName); if(!m)throw new Error("Mask not found"); return m;
  }
  function interpolation(name){
    var n=String(name||"LINEAR").toUpperCase(); if(n==="HOLD")return KeyframeInterpolationType.HOLD; if(n==="BEZIER")return KeyframeInterpolationType.BEZIER; return KeyframeInterpolationType.LINEAR;
  }
  function easeArray(v){
    var src=v instanceof Array?v:[v]; var out=[]; for(var i=0;i<src.length;i++){var x=src[i];out.push(new KeyframeEase(Number(x.speed||0),Number(x.influence||33.333)));}return out;
  }
  function textJustification(name){
    if(name===undefined)return null; var n=String(name).toUpperCase();
    if(ParagraphJustification[n]!==undefined)return ParagraphJustification[n];
    if(ParagraphJustification[n+"_JUSTIFY"]!==undefined)return ParagraphJustification[n+"_JUSTIFY"];
    return null;
  }
  function maskMode(name){
    if(name===undefined)return null; var n=String(name).toUpperCase();
    if(MaskMode[n]!==undefined)return MaskMode[n];
    return null;
  }
  function trackMatteType(name){
    if(name===undefined||typeof TrackMatteType==="undefined")return null; var n=String(name).toUpperCase();
    if(TrackMatteType[n]!==undefined)return TrackMatteType[n];
    return null;
  }
  function setTextDoc(l,a){
    var tp=l.property("ADBE Text Properties").property("ADBE Text Document"); var td=tp.value;
    if(a.text!==undefined)td.text=String(a.text); if(a.font!==undefined)td.font=String(a.font); if(a.fontSize!==undefined)td.fontSize=Number(a.fontSize);
    if(a.fillColor!==undefined)td.fillColor=a.fillColor; if(a.strokeColor!==undefined)td.strokeColor=a.strokeColor;
    if(a.applyFill!==undefined)td.applyFill=!!a.applyFill; if(a.applyStroke!==undefined)td.applyStroke=!!a.applyStroke;
    if(a.strokeWidth!==undefined)td.strokeWidth=Number(a.strokeWidth); if(a.tracking!==undefined)td.tracking=Number(a.tracking);
    if(a.leading!==undefined){td.autoLeading=false;td.leading=Number(a.leading);} if(a.autoLeading!==undefined)td.autoLeading=!!a.autoLeading;
    if(a.fauxBold!==undefined)td.fauxBold=!!a.fauxBold; if(a.fauxItalic!==undefined)td.fauxItalic=!!a.fauxItalic;
    if(a.baselineShift!==undefined)td.baselineShift=Number(a.baselineShift); if(a.horizontalScale!==undefined)td.horizontalScale=Number(a.horizontalScale); if(a.verticalScale!==undefined)td.verticalScale=Number(a.verticalScale);
    var j=textJustification(a.justification); if(j!==null)td.justification=j;
    tp.setValue(td);
  }
  function setTransform(l,a){
    var tr=l.property("ADBE Transform Group");
    if(a.anchorPoint!==undefined)tr.property("ADBE Anchor Point").setValue(a.anchorPoint);
    if(a.position!==undefined)tr.property("ADBE Position").setValue(a.position);
    if(a.scale!==undefined)tr.property("ADBE Scale").setValue(a.scale);
    if(a.rotation!==undefined){var r=tr.property("ADBE Rotate Z")||tr.property("ADBE Rotation");if(r)r.setValue(a.rotation);}
    if(a.opacity!==undefined)tr.property("ADBE Opacity").setValue(a.opacity);
  }
  function doAction(a){
    var c,l,p,e,rq,om,indices;
    switch(a.op){
      case "newProject": if(app.project)app.project.close(CloseOptions.DO_NOT_SAVE_CHANGES);app.newProject();break;
      case "openProject": app.open(new File(a.path));break;
      case "save": app.project.save();break;
      case "saveAs": app.project.save(new File(a.path));break;
      case "importFile":
        var io=new ImportOptions(new File(a.path)); if(a.sequence!==undefined)io.sequence=!!a.sequence; var it=app.project.importFile(io); if(a.name)it.name=a.name; break;
      case "createFolder": app.project.items.addFolder(a.name);break;
      case "createComp": app.project.items.addComp(a.name,Number(a.width),Number(a.height),Number(a.pixelAspect||1),Number(a.duration),Number(a.fps));break;
      case "addFootageLayer": c=comp(a.comp); l=c.layers.add(item(a.item)); if(a.name)l.name=a.name; break;
      case "addTextLayer": c=comp(a.comp); l=c.layers.addText(a.text||""); if(a.name)l.name=a.name; break;
      case "addSolidLayer": c=comp(a.comp); l=c.layers.addSolid(a.color||[1,1,1],a.name||"Solid",Number(a.width||c.width),Number(a.height||c.height),Number(a.pixelAspect||1),Number(a.duration||c.duration));break;
      case "addNullLayer": c=comp(a.comp); l=c.layers.addNull(Number(a.duration||c.duration)); if(a.name)l.name=a.name;break;
      case "addShapeLayer": c=comp(a.comp); l=c.layers.addShape(); if(a.name)l.name=a.name;break;
      case "addCamera": c=comp(a.comp); l=c.layers.addCamera(a.name||"Camera",a.center||[c.width/2,c.height/2]);break;
      case "addLight": c=comp(a.comp); l=c.layers.addLight(a.name||"Light",a.center||[c.width/2,c.height/2]);break;
      case "setLayerTiming": c=comp(a.comp);l=layer(c,a);if(a.startTime!==undefined)l.startTime=Number(a.startTime);if(a.inPoint!==undefined)l.inPoint=Number(a.inPoint);if(a.outPoint!==undefined)l.outPoint=Number(a.outPoint);if(a.stretch!==undefined)l.stretch=Number(a.stretch);break;
      case "setTransform": c=comp(a.comp);l=layer(c,a);setTransform(l,a);break;
      case "setLayerSwitches":
        c=comp(a.comp);l=layer(c,a);
        if(a.threeDLayer!==undefined)l.threeDLayer=!!a.threeDLayer;if(a.motionBlur!==undefined)l.motionBlur=!!a.motionBlur;if(a.adjustmentLayer!==undefined)l.adjustmentLayer=!!a.adjustmentLayer;
        if(a.guideLayer!==undefined)l.guideLayer=!!a.guideLayer;if(a.shy!==undefined)l.shy=!!a.shy;if(a.solo!==undefined)l.solo=!!a.solo;if(a.enabled!==undefined)l.enabled=!!a.enabled;
        if(a.collapseTransformation!==undefined)l.collapseTransformation=!!a.collapseTransformation;if(a.locked!==undefined)l.locked=!!a.locked;if(a.audioEnabled!==undefined)l.audioEnabled=!!a.audioEnabled;
        if(a.label!==undefined)l.label=Number(a.label);if(a.blendingMode!==undefined&&BlendingMode[String(a.blendingMode)])l.blendingMode=BlendingMode[String(a.blendingMode)];break;
      case "setTextDocument": c=comp(a.comp);l=layer(c,a);setTextDoc(l,a);break;
      case "setProperty": c=comp(a.comp);l=layer(c,a);p=prop(l,a.path);if(a.time!==undefined)p.setValueAtTime(Number(a.time),a.value);else p.setValue(a.value);break;
      case "addProperty": c=comp(a.comp);l=layer(c,a);var pg=prop(l,a.parentPath||[]);if(!pg.canAddProperty||!pg.canAddProperty(a.matchName))throw new Error("Cannot add property: "+a.matchName);var np=pg.addProperty(a.matchName);if(a.propertyName)np.name=a.propertyName;break;
      case "removeProperty": c=comp(a.comp);l=layer(c,a);p=prop(l,a.path);p.remove();break;
      case "duplicateProperty": c=comp(a.comp);l=layer(c,a);p=prop(l,a.path);if(!p.duplicate)throw new Error("Property cannot be duplicated");p.duplicate();break;
      case "moveProperty": c=comp(a.comp);l=layer(c,a);p=prop(l,a.path);if(!p.moveTo)throw new Error("Property cannot be moved");p.moveTo(Number(a.index));break;
      case "setExpression": c=comp(a.comp);l=layer(c,a);p=prop(l,a.path);p.expression=a.expression;p.expressionEnabled=a.enabled!==false;break;
      case "addKeyframe": c=comp(a.comp);l=layer(c,a);p=prop(l,a.path);p.setValueAtTime(Number(a.time),a.value);break;
      case "removeKeyframe": c=comp(a.comp);l=layer(c,a);p=prop(l,a.path);p.removeKey(Number(a.keyIndex));break;
      case "setKeyframeInterpolation": c=comp(a.comp);l=layer(c,a);p=prop(l,a.path);var ki=a.keyIndex?Number(a.keyIndex):p.nearestKeyIndex(Number(a.time));p.setInterpolationTypeAtKey(ki,interpolation(a.inType),interpolation(a.outType||a.inType));break;
      case "setKeyframeEase": c=comp(a.comp);l=layer(c,a);p=prop(l,a.path);var kei=a.keyIndex?Number(a.keyIndex):p.nearestKeyIndex(Number(a.time));p.setTemporalEaseAtKey(kei,easeArray(a.inEase||{speed:0,influence:33.333}),easeArray(a.outEase||a.inEase||{speed:0,influence:33.333}));break;
      case "setSpatialTangents": c=comp(a.comp);l=layer(c,a);p=prop(l,a.path);var ksi=a.keyIndex?Number(a.keyIndex):p.nearestKeyIndex(Number(a.time));p.setSpatialTangentsAtKey(ksi,a.inTangent,a.outTangent);break;
      case "addMask": c=comp(a.comp);l=layer(c,a);var mg=l.property("ADBE Mask Parade");var mk=mg.addProperty("Mask");if(a.maskName)mk.name=a.maskName;var md=maskMode(a.mode);if(md!==null)mk.maskMode=md;if(a.inverted!==undefined)mk.inverted=!!a.inverted;if(a.shape)mk.property("ADBE Mask Shape").setValue(shapeFrom(a.shape));break;
      case "setMaskPath": c=comp(a.comp);l=layer(c,a);var mm=targetMask(l,a);p=mm.property("ADBE Mask Shape");if(a.time!==undefined)p.setValueAtTime(Number(a.time),shapeFrom(a.shape));else p.setValue(shapeFrom(a.shape));break;
      case "setMaskProperties": c=comp(a.comp);l=layer(c,a);var mp=targetMask(l,a);if(a.opacity!==undefined)mp.property("ADBE Mask Opacity").setValue(Number(a.opacity));if(a.feather!==undefined)mp.property("ADBE Mask Feather").setValue(a.feather);if(a.expansion!==undefined)mp.property("ADBE Mask Offset").setValue(Number(a.expansion));if(a.inverted!==undefined)mp.inverted=!!a.inverted;break;
      case "enableTimeRemap": c=comp(a.comp);l=layer(c,a);l.timeRemapEnabled=a.enabled!==false;break;
      case "setCompWorkArea": c=comp(a.comp);if(a.start!==undefined)c.workAreaStart=Number(a.start);if(a.duration!==undefined)c.workAreaDuration=Number(a.duration);break;
      case "setCompProperties": c=comp(a.comp);if(a.duration!==undefined)c.duration=Number(a.duration);if(a.frameRate!==undefined)c.frameRate=Number(a.frameRate);if(a.displayStartTime!==undefined)c.displayStartTime=Number(a.displayStartTime);if(a.motionBlur!==undefined)c.motionBlur=!!a.motionBlur;break;
      case "addMarker": c=comp(a.comp);l=layer(c,a);p=l.property("ADBE Marker");var mv=new MarkerValue(a.comment||"");if(a.chapter)mv.chapter=a.chapter;if(a.url)mv.url=a.url;p.setValueAtTime(Number(a.time),mv);break;
      case "addEffect": c=comp(a.comp);l=layer(c,a);e=l.property("ADBE Effect Parade").addProperty(a.matchName);if(a.name)e.name=a.name;break;
      case "setEffectProperty": c=comp(a.comp);l=layer(c,a);var fx=l.property("ADBE Effect Parade");e=a.effectIndex?fx.property(Number(a.effectIndex)):fx.property(a.effectName);if(!e)throw new Error("Effect not found");p=e.property(a.property);if(!p)throw new Error("Effect property not found: "+a.property);if(a.time!==undefined)p.setValueAtTime(Number(a.time),a.value);else p.setValue(a.value);break;
      case "precompose": c=comp(a.comp);indices=arr(a.layerIndices);c.layers.precompose(indices,a.name,a.moveAllAttributes!==false);break;
      case "duplicateLayer": c=comp(a.comp);l=layer(c,a);l.duplicate();break;
      case "removeLayer": c=comp(a.comp);l=layer(c,a);l.remove();break;
      case "setParent": c=comp(a.comp);l=layer(c,a);l.parent=layer(c,{name:a.parentName,index:a.parentIndex});break;
      case "reorderLayer": c=comp(a.comp);l=layer(c,a);if(a.beforeName||a.beforeIndex)l.moveBefore(layer(c,{name:a.beforeName,index:a.beforeIndex}));else if(a.afterName||a.afterIndex)l.moveAfter(layer(c,{name:a.afterName,index:a.afterIndex}));else if(a.position==="beginning")l.moveToBeginning();else if(a.position==="end")l.moveToEnd();else throw new Error("reorderLayer target required");break;
      case "replaceSource": c=comp(a.comp);l=layer(c,a);if(!l.replaceSource)throw new Error("Layer does not support replaceSource");l.replaceSource(item(a.item),a.fixExpressions!==false);break;
      case "setTrackMatte": c=comp(a.comp);l=layer(c,a);var matte=layer(c,{name:a.matteName,index:a.matteIndex});var mt=trackMatteType(a.matteType);if(!l.setTrackMatte||mt===null)throw new Error("Track matte API unavailable");l.setTrackMatte(matte,mt);break;
      case "removeTrackMatte": c=comp(a.comp);l=layer(c,a);if(!l.removeTrackMatte)throw new Error("Track matte API unavailable");l.removeTrackMatte();break;
      case "queueRender":
        c=comp(a.comp);rq=app.project.renderQueue.items.add(c);if(a.renderSettingsTemplate)rq.applyTemplate(a.renderSettingsTemplate);om=rq.outputModule(1);if(a.outputModuleTemplate)om.applyTemplate(a.outputModuleTemplate);if(a.outputPath)om.file=new File(a.outputPath);break;
      case "setRenderQueueItem": rq=app.project.renderQueue.item(Number(a.itemIndex||1));if(!rq)throw new Error("Render queue item not found");if(a.render!==undefined)rq.render=!!a.render;if(a.timeSpanStart!==undefined)rq.timeSpanStart=Number(a.timeSpanStart);if(a.timeSpanDuration!==undefined)rq.timeSpanDuration=Number(a.timeSpanDuration);if(a.skipFrames!==undefined)rq.skipFrames=Number(a.skipFrames);if(a.settings)rq.setSettings(a.settings);break;
      case "setOutputModule": rq=app.project.renderQueue.item(Number(a.itemIndex||1));if(!rq)throw new Error("Render queue item not found");om=rq.outputModule(Number(a.outputModuleIndex||1));if(a.template)om.applyTemplate(a.template);if(a.path)om.file=new File(a.path);if(a.settings)om.setSettings(a.settings);break;
      case "renderQueueRender": app.project.renderQueue.render();break;
      case "executeMenuCommand": var id=a.commandId!==undefined?Number(a.commandId):app.findMenuCommandId(a.commandName);if(!id)throw new Error("Menu command not found: "+a.commandName);app.executeCommand(id);break;
      default: throw new Error("Unsupported AE action: "+a.op);
    }
    return {op:a.op,ok:true};
  }

  try{
    app.beginUndoGroup(PAYLOAD.undoGroup||"Autonomous Editor");
    for(var i=0;i<PAYLOAD.actions.length;i++) result.actions.push(doAction(PAYLOAD.actions[i]));
    app.endUndoGroup();
  }catch(err){
    try{app.endUndoGroup();}catch(_){}
    result.ok=false;result.error=String(err);result.line=err.line||null;
  }
  try{writeResult();}catch(_){}
})();
'''

def js_string(s: str) -> str:
    return json.dumps(str(s).replace("\\", "/"), ensure_ascii=False)

def compile_jsx(plan: dict, result_file: Path) -> str:
    payload = json.dumps(plan, ensure_ascii=False, separators=(",", ":"))
    return JS_RUNTIME.replace("__PAYLOAD__", payload).replace("__RESULT_FILE__", js_string(str(result_file)))

def dispatch(afterfx: str, jsx_path: Path, result_path: Path, timeout: float) -> dict:
    subprocess.Popen([afterfx, "-r", str(jsx_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if result_path.exists():
            try:
                return json.loads(result_path.read_text(encoding="utf-8-sig"))
            except Exception:
                pass
        time.sleep(0.25)
    return {"ok": False, "error": f"Timed out waiting for AE result after {timeout}s", "resultFile": str(result_path)}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan", help="JSON action plan")
    ap.add_argument("--afterfx")
    ap.add_argument("--out-jsx")
    ap.add_argument("--result")
    ap.add_argument("--timeout", type=float, default=120)
    ap.add_argument("--compile-only", action="store_true")
    ns = ap.parse_args()
    plan_path = Path(ns.plan).resolve(); plan = json.loads(plan_path.read_text(encoding="utf-8"))
    work = plan_path.parent
    result = Path(ns.result).resolve() if ns.result else work / f"ae-result-{uuid.uuid4().hex}.json"
    jsx = Path(ns.out_jsx).resolve() if ns.out_jsx else work / f"ae-job-{uuid.uuid4().hex}.jsx"
    jsx.write_text(compile_jsx(plan, result), encoding="utf-8")
    if ns.compile_only:
        print(json.dumps({"ok": True, "jsx": str(jsx), "result": str(result)}, indent=2)); return
    if not ns.afterfx:
        raise SystemExit("--afterfx is required unless --compile-only is used")
    output = dispatch(ns.afterfx, jsx, result, ns.timeout)
    print(json.dumps(output, indent=2, ensure_ascii=False))
    raise SystemExit(0 if output.get("ok") else 2)

if __name__ == "__main__": main()
