/* Autonomous Editor Bridge for Premiere UXP.
 * Explicit operation registry only: no eval, no arbitrary script execution.
 * Each operation is designed to be independently feature-detected and verified.
 */
const ppro = require("premierepro");
const { host, versions } = require("uxp");
const cfg = require("./runtime-config.js");

const statusEl = document.getElementById("status");
let socket = null;
let reconnectTimer = null;

function setStatus(text) { if (statusEl) statusEl.textContent = text; }
function guidString(g) { try { return g && g.toString ? g.toString() : String(g); } catch (_) { return String(g); } }
function tick(seconds) { return ppro.TickTime.createWithSeconds(Number(seconds || 0)); }

async function activeProject() {
  const p = await ppro.Project.getActiveProject();
  if (!p) throw new Error("No active Premiere project");
  return p;
}

async function sequenceByGuid(project, guid) {
  if (!guid) {
    const seq = await project.getActiveSequence();
    if (!seq) throw new Error("No active sequence");
    return seq;
  }
  const seqs = await project.getSequences();
  const hit = seqs.find(s => guidString(s.guid) === String(guid));
  if (!hit) throw new Error(`Sequence not found: ${guid}`);
  return hit;
}

async function itemId(item) { try { return await item.getId(); } catch (_) { return null; } }

async function walkItems(folder, out) {
  const children = await folder.getItems();
  for (const item of children) {
    const id = await itemId(item);
    const row = { id, name: item.name, type: item.type };
    let wasFolder = false;
    try {
      const f = ppro.FolderItem.cast(item);
      const grand = await f.getItems();
      row.kind = "folder";
      row.childCount = grand.length;
      out.push(row);
      await walkItems(f, out);
      wasFolder = true;
    } catch (_) {}
    if (wasFolder) continue;
    try {
      const clip = ppro.ClipProjectItem.cast(item);
      row.kind = "clip";
      row.mediaPath = await clip.getMediaFilePath();
      try { row.offline = await clip.isOffline(); } catch (_) {}
      try { row.proxyPath = await clip.getProxyPath(); } catch (_) {}
    } catch (_) { row.kind = row.kind || "projectItem"; }
    out.push(row);
  }
}

async function findProjectItem(project, wantedId) {
  if (!wantedId) throw new Error("projectItemId is required");
  const root = await project.getRootItem();
  async function recur(folder) {
    for (const item of await folder.getItems()) {
      if (String(await itemId(item)) === String(wantedId)) return item;
      try {
        const f = ppro.FolderItem.cast(item);
        const hit = await recur(f);
        if (hit) return hit;
      } catch (_) {}
    }
    return null;
  }
  const hit = await recur(root);
  if (!hit) throw new Error(`Project item not found: ${wantedId}`);
  return hit;
}

async function targetBin(project, id) {
  if (!id) return await project.getRootItem();
  const item = await findProjectItem(project, id);
  return ppro.FolderItem.cast(item);
}

function transact(project, action, label) {
  const ok = project.executeTransaction(compound => { compound.addAction(action); }, label || "Autonomous Editor");
  if (!ok) throw new Error(`Transaction rejected: ${label || "Autonomous Editor"}`);
  return ok;
}

async function timelineItem(sequence, mediaType, trackIndex, itemIndex) {
  const constants = ppro.Constants;
  const track = mediaType === "audio" ? await sequence.getAudioTrack(Number(trackIndex)) : await sequence.getVideoTrack(Number(trackIndex));
  if (!track) throw new Error(`Track not found: ${mediaType} ${trackIndex}`);
  const items = track.getTrackItems(constants.TrackItemType.CLIP, false);
  const item = items[Number(itemIndex)];
  if (!item) throw new Error(`Track item not found: ${mediaType} ${trackIndex}:${itemIndex}`);
  return { track, item };
}

async function summarizeTrackItem(item, index) {
  const pi = await item.getProjectItem();
  return {
    index,
    name: await item.getName(),
    projectItemId: pi ? await itemId(pi) : null,
    start: (await item.getStartTime()).seconds,
    end: (await item.getEndTime()).seconds,
    inPoint: (await item.getInPoint()).seconds,
    outPoint: (await item.getOutPoint()).seconds,
    speed: await item.getSpeed(),
    disabled: await item.isDisabled()
  };
}

async function componentSnapshot(chain) {
  const out = [];
  const count = chain.getComponentCount();
  for (let i = 0; i < count; i++) {
    const c = chain.getComponentAtIndex(i);
    const params = [];
    const pc = c.getParamCount();
    for (let p = 0; p < pc; p++) {
      const param = c.getParam(p);
      let value = null;
      try { value = await param.getStartValue(); } catch (_) {}
      params.push({ index: p, displayName: param.displayName, value });
    }
    out.push({ index: i, displayName: await c.getDisplayName(), matchName: await c.getMatchName(), params });
  }
  return out;
}

const handlers = {
  async ping(args) { return { pong: true, premiereVersion: host.version, uxpVersion: versions.uxp, bridgeVersion: cfg.bridgeVersion, echo: args || null }; },
  async hostInfo() { return { premiereVersion: host.version, uxpVersion: versions.uxp, bridgeVersion: cfg.bridgeVersion }; },

  async capabilities() {
    const caps = {
      project: !!ppro.Project, sequenceEditor: !!ppro.SequenceEditor, markers: !!ppro.Markers,
      videoFilters: !!ppro.VideoFilterFactory, audioFilters: !!ppro.AudioFilterFactory,
      transitions: !!ppro.TransitionFactory, exporter: !!ppro.Exporter, encoderManager: !!ppro.EncoderManager,
      projectConverter: !!ppro.ProjectConverter, transcript: !!ppro.Transcript, metadata: !!ppro.Metadata, hybridHostPossible: Number(String(host.version).split(".")[0]) >= 26
    };
    try { caps.isAEInstalled = await ppro.Utils.isAEInstalled(); } catch (_) {}
    return caps;
  },

  async createProject(args) {
    const p = await ppro.Project.createProject(args.path);
    return { name: p.name, path: p.path, guid: guidString(p.guid) };
  },
  async openProject(args) {
    const p = await ppro.Project.open(args.path);
    return { name: p.name, path: p.path, guid: guidString(p.guid) };
  },
  async saveProject() { const p = await activeProject(); return { saved: await p.save(), path: p.path }; },
  async saveProjectAs(args) { const p = await activeProject(); return { saved: await p.saveAs(args.path), path: p.path }; },

  async projectState() {
    const p = await activeProject();
    const seqs = await p.getSequences();
    const active = await p.getActiveSequence();
    return {
      project: { name: p.name, path: p.path, guid: guidString(p.guid) },
      activeSequenceGuid: active ? guidString(active.guid) : null,
      sequences: await Promise.all(seqs.map(async s => ({
        name: s.name, guid: guidString(s.guid),
        videoTracks: await s.getVideoTrackCount(), audioTracks: await s.getAudioTrackCount(),
        endSeconds: (await s.getEndTime()).seconds
      })))
    };
  },

  async listProjectItems() {
    const p = await activeProject(); const out = [];
    await walkItems(await p.getRootItem(), out);
    return out;
  },

  async importFiles(args) {
    const p = await activeProject();
    const bin = await targetBin(p, args.targetBinId);
    const ok = await p.importFiles(args.paths || [], args.suppressUI !== false, bin, !!args.asNumberedStills);
    return { imported: ok };
  },

  async renameProjectItem(args) {
    const p = await activeProject(); const item = await findProjectItem(p, args.projectItemId);
    transact(p, ppro.ProjectItem.cast(item).createSetNameAction(String(args.name)), "Rename project item");
    return { id: await itemId(item), name: item.name };
  },

  async setProjectItemLabel(args) {
    const p = await activeProject(); const item = await findProjectItem(p, args.projectItemId);
    transact(p, ppro.ProjectItem.cast(item).createSetColorLabelAction(Number(args.colorLabelIndex)), "Set project item label");
    return { id: await itemId(item), colorLabelIndex: await ppro.ProjectItem.cast(item).getColorLabelIndex() };
  },

  async moveProjectItem(args) {
    const p = await activeProject(); const item = await findProjectItem(p, args.projectItemId); const dest = await targetBin(p, args.targetBinId);
    const parent = await ppro.ProjectItem.cast(item).getParentBin();
    transact(p, parent.createMoveItemAction(ppro.ProjectItem.cast(item), dest), "Move project item");
    return { ok: true };
  },

  async removeProjectItem(args) {
    const p = await activeProject(); const item = await findProjectItem(p, args.projectItemId); const parent = await ppro.ProjectItem.cast(item).getParentBin();
    transact(p, parent.createRemoveItemAction(ppro.ProjectItem.cast(item)), "Remove project item");
    return { ok: true };
  },

  async attachProxy(args) {
    const p = await activeProject(); const clip = ppro.ClipProjectItem.cast(await findProjectItem(p, args.projectItemId));
    return { attached: await clip.attachProxy(args.mediaPath, !!args.isHiRes, !!args.makeAlternateLinkInTeamProjects) };
  },

  async changeMediaPath(args) {
    const p = await activeProject(); const clip = ppro.ClipProjectItem.cast(await findProjectItem(p, args.projectItemId));
    return { changed: await clip.changeMediaFilePath(args.newPath, !!args.overrideCompatibilityCheck) };
  },

  async refreshMedia(args) {
    const p = await activeProject(); const clip = ppro.ClipProjectItem.cast(await findProjectItem(p, args.projectItemId));
    return { refreshed: await clip.refreshMedia() };
  },

  async createSubclip(args) {
    const p = await activeProject(); const clip = ppro.ClipProjectItem.cast(await findProjectItem(p, args.projectItemId));
    if (!clip.createSubClipAction) throw new Error("createSubClipAction requires Premiere 26.3+");
    const action = clip.createSubClipAction(String(args.name), tick(args.startSeconds), tick(args.endSeconds), args.hasHardBoundaries !== false, {takeVideo: args.takeVideo !== false, takeAudio: args.takeAudio !== false});
    transact(p, action, "Create subclip"); return { ok: true };
  },

  async transcribeProjectItem(args) {
    const p = await activeProject(); const clip = ppro.ClipProjectItem.cast(await findProjectItem(p, args.projectItemId));
    if (!ppro.Transcript) throw new Error("Transcript API unavailable");
    const options = {}; if (args.languageCode) options.languageCode = args.languageCode;
    return { started: await ppro.Transcript.transcribeClipProjectItem(clip, options) };
  },

  async exportTranscript(args) {
    const p = await activeProject(); const clip = ppro.ClipProjectItem.cast(await findProjectItem(p, args.projectItemId));
    if (!ppro.Transcript) throw new Error("Transcript API unavailable");
    return { json: await ppro.Transcript.exportToJSON(clip), hasTranscript: ppro.Transcript.hasTranscript ? ppro.Transcript.hasTranscript(clip) : null };
  },

  async importTranscriptJSON(args) {
    const p = await activeProject(); const clip = ppro.ClipProjectItem.cast(await findProjectItem(p, args.projectItemId));
    if (!ppro.Transcript) throw new Error("Transcript API unavailable");
    const segments = ppro.Transcript.importFromJSON(String(args.json));
    transact(p, ppro.Transcript.createImportTextSegmentsAction(segments, clip), "Import transcript");
    return { ok: true };
  },

  async transcriptionLanguages() {
    if (!ppro.Transcript) throw new Error("Transcript API unavailable");
    return { supported: ppro.Transcript.querySupportedLanguages ? ppro.Transcript.querySupportedLanguages() : null };
  },

  async createBin(args) {
    const p = await activeProject(); const bin = await targetBin(p, args.parentBinId);
    transact(p, bin.createBinAction(args.name, args.makeUnique !== false), `Create bin ${args.name}`);
    return { ok: true };
  },

  async createSequence(args) {
    const p = await activeProject();
    let seq;
    if (args.presetPath && p.createSequenceWithPresetPath) seq = await p.createSequenceWithPresetPath(args.name, args.presetPath);
    else seq = await p.createSequence(args.name, args.presetPath || "");
    return { name: seq.name, guid: guidString(seq.guid) };
  },

  async createSequenceFromMedia(args) {
    const p = await activeProject(); const bin = await targetBin(p, args.targetBinId);
    const clips = [];
    for (const id of (args.projectItemIds || [])) clips.push(ppro.ClipProjectItem.cast(await findProjectItem(p, id)));
    const seq = await p.createSequenceFromMedia(args.name, clips, bin);
    return { name: seq.name, guid: guidString(seq.guid) };
  },

  async openSequence(args) { const p = await activeProject(); const s = await sequenceByGuid(p, args.sequenceGuid); return { opened: await p.openSequence(s) }; },
  async setActiveSequence(args) { const p = await activeProject(); const s = await sequenceByGuid(p, args.sequenceGuid); return { active: await p.setActiveSequence(s) }; },
  async deleteSequence(args) { const p = await activeProject(); const s = await sequenceByGuid(p, args.sequenceGuid); return { deleted: await p.deleteSequence(s) }; },
  async closeSequence(args) { const p = await activeProject(); if (!p.closeSequence) throw new Error("closeSequence requires Premiere 26.2+"); const s = await sequenceByGuid(p, args.sequenceGuid); return { closed: await p.closeSequence(s) }; },

  async getSequenceSettings(args) {
    const p = await activeProject(); const s = await sequenceByGuid(p, args.sequenceGuid); const st = await s.getSettings();
    const rect = await st.getVideoFrameRect(); const fr = st.getVideoFrameRate ? await st.getVideoFrameRate() : null;
    return {
      editingMode: await st.getEditingMode(), maximumBitDepth: await st.getMaximumBitDepth(), maxRenderQuality: await st.getMaxRenderQuality(),
      compositeInLinearColor: await st.getCompositeInLinearColor(), videoFrameRect: rect ? {width:rect.width, height:rect.height} : null,
      videoPixelAspectRatio: await st.getVideoPixelAspectRatio(), videoFrameRate: fr ? fr.value : null,
      previewCodec: await st.getPreviewCodec(), previewFileFormat: await st.getPreviewFileFormat()
    };
  },

  async setSequenceQuality(args) {
    const p = await activeProject(); const s = await sequenceByGuid(p, args.sequenceGuid); const st = await s.getSettings();
    if (args.maximumBitDepth !== undefined) await st.setMaximumBitDepth(!!args.maximumBitDepth);
    if (args.maxRenderQuality !== undefined) await st.setMaxRenderQuality(!!args.maxRenderQuality);
    if (args.compositeInLinearColor !== undefined) await st.setCompositeInLinearColor(!!args.compositeInLinearColor);
    if (args.editingMode !== undefined) await st.setEditingMode(String(args.editingMode));
    transact(p, s.createSetSettingsAction(st), "Set sequence quality"); return { ok: true };
  },

  async renameTrack(args) {
    const p = await activeProject(); const s = await sequenceByGuid(p, args.sequenceGuid);
    const tr = args.mediaType === "audio" ? await s.getAudioTrack(Number(args.trackIndex)) : (args.mediaType === "caption" ? await s.getCaptionTrack(Number(args.trackIndex)) : await s.getVideoTrack(Number(args.trackIndex)));
    if (!tr.createSetNameAction) throw new Error("Track rename requires Premiere 26.3+");
    transact(p, tr.createSetNameAction(String(args.name)), "Rename track"); return { ok: true, name: tr.name };
  },

  async listTimeline(args) {
    const p = await activeProject(); const s = await sequenceByGuid(p, args.sequenceGuid);
    const videos = [], audios = [];
    for (let t = 0; t < await s.getVideoTrackCount(); t++) {
      const tr = await s.getVideoTrack(t); const items = tr.getTrackItems(ppro.Constants.TrackItemType.CLIP, false);
      videos.push({ index: t, name: tr.name, muted: await tr.isMuted(), items: await Promise.all(items.map((x, i) => summarizeTrackItem(x, i))) });
    }
    for (let t = 0; t < await s.getAudioTrackCount(); t++) {
      const tr = await s.getAudioTrack(t); const items = tr.getTrackItems(ppro.Constants.TrackItemType.CLIP, false);
      audios.push({ index: t, name: tr.name, muted: await tr.isMuted(), items: await Promise.all(items.map((x, i) => summarizeTrackItem(x, i))) });
    }
    return { sequence: { name: s.name, guid: guidString(s.guid) }, videoTracks: videos, audioTracks: audios };
  },

  async insertProjectItem(args) {
    const p = await activeProject(); const s = await sequenceByGuid(p, args.sequenceGuid);
    const pi = await findProjectItem(p, args.projectItemId); const editor = ppro.SequenceEditor.getEditor(s);
    const at = tick(args.timeSeconds);
    const action = args.mode === "overwrite"
      ? editor.createOverwriteItemAction(pi, at, Number(args.videoTrackIndex || 0), Number(args.audioTrackIndex || 0))
      : editor.createInsertProjectItemAction(pi, at, Number(args.videoTrackIndex || 0), Number(args.audioTrackIndex || 0), !!args.limitShift);
    transact(p, action, `${args.mode === "overwrite" ? "Overwrite" : "Insert"} project item`);
    return { ok: true };
  },

  async setProjectItemInOut(args) {
    const p = await activeProject(); const clip = ppro.ClipProjectItem.cast(await findProjectItem(p, args.projectItemId));
    const action = clip.createSetInOutPointsAction(tick(args.inSeconds), tick(args.outSeconds));
    transact(p, action, "Set project item in/out"); return { ok: true };
  },

  async editTrackItem(args) {
    const p = await activeProject(); const s = await sequenceByGuid(p, args.sequenceGuid);
    const { item } = await timelineItem(s, args.mediaType || "video", args.trackIndex || 0, args.itemIndex || 0);
    const actions = [];
    if (args.startSeconds !== undefined) actions.push(item.createSetStartAction(tick(args.startSeconds)));
    if (args.endSeconds !== undefined) actions.push(item.createSetEndAction(tick(args.endSeconds)));
    if (args.inSeconds !== undefined) actions.push(item.createSetInPointAction(tick(args.inSeconds)));
    if (args.outSeconds !== undefined) actions.push(item.createSetOutPointAction(tick(args.outSeconds)));
    if (args.moveBySeconds !== undefined) actions.push(item.createMoveAction(tick(args.moveBySeconds)));
    if (args.disabled !== undefined) actions.push(item.createSetDisabledAction(!!args.disabled));
    if (args.name !== undefined) actions.push(item.createSetNameAction(String(args.name)));
    const ok = p.executeTransaction(c => { actions.forEach(a => c.addAction(a)); }, "Edit track item");
    if (!ok) throw new Error("Track item transaction rejected");
    return await summarizeTrackItem(item, Number(args.itemIndex || 0));
  },

  async setTrackMute(args) {
    const p = await activeProject(); const s = await sequenceByGuid(p, args.sequenceGuid);
    const tr = args.mediaType === "audio" ? await s.getAudioTrack(Number(args.trackIndex)) : await s.getVideoTrack(Number(args.trackIndex));
    return { muted: await tr.setMute(!!args.muted) };
  },

  async addMarker(args) {
    const p = await activeProject(); const s = await sequenceByGuid(p, args.sequenceGuid);
    const markers = await ppro.Markers.getMarkers(s);
    const action = markers.createAddMarkerAction(args.name || "Marker", args.markerType || "Comment", tick(args.startSeconds), tick(args.durationSeconds || 0), args.comments || "");
    transact(p, action, "Add marker"); return { ok: true };
  },

  async setSequenceRange(args) {
    const p = await activeProject(); const s = await sequenceByGuid(p, args.sequenceGuid); const actions = [];
    if (args.inSeconds !== undefined) actions.push(s.createSetInPointAction(tick(args.inSeconds)));
    if (args.outSeconds !== undefined) actions.push(s.createSetOutPointAction(tick(args.outSeconds)));
    const ok = p.executeTransaction(c => actions.forEach(a => c.addAction(a)), "Set sequence range");
    if (!ok) throw new Error("Sequence range transaction rejected"); return { ok: true };
  },
  async setPlayhead(args) { const p = await activeProject(); const s = await sequenceByGuid(p, args.sequenceGuid); return { ok: await s.setPlayerPosition(tick(args.seconds)) }; },

  async listVideoEffects() { return { displayNames: await ppro.VideoFilterFactory.getDisplayNames(), matchNames: await ppro.VideoFilterFactory.getMatchNames() }; },
  async listAudioEffects() { return { displayNames: await ppro.AudioFilterFactory.getDisplayNames() }; },
  async listVideoTransitions() { return { matchNames: await ppro.TransitionFactory.getVideoTransitionMatchNames() }; },

  async getComponents(args) {
    const p = await activeProject(); const s = await sequenceByGuid(p, args.sequenceGuid);
    const { item } = await timelineItem(s, args.mediaType || "video", args.trackIndex || 0, args.itemIndex || 0);
    return await componentSnapshot(await item.getComponentChain());
  },

  async addEffect(args) {
    const p = await activeProject(); const s = await sequenceByGuid(p, args.sequenceGuid);
    const { item } = await timelineItem(s, args.mediaType || "video", args.trackIndex || 0, args.itemIndex || 0);
    const chain = await item.getComponentChain(); let component;
    if ((args.mediaType || "video") === "audio") component = await ppro.AudioFilterFactory.createComponentByDisplayName(args.displayName, item);
    else component = await ppro.VideoFilterFactory.createComponent(args.matchName);
    transact(p, chain.createAppendComponentAction(component), "Add effect");
    return { ok: true, components: await componentSnapshot(await item.getComponentChain()) };
  },

  async setEffectParam(args) {
    const p = await activeProject(); const s = await sequenceByGuid(p, args.sequenceGuid);
    const { item } = await timelineItem(s, args.mediaType || "video", args.trackIndex || 0, args.itemIndex || 0);
    const chain = await item.getComponentChain(); const component = chain.getComponentAtIndex(Number(args.componentIndex));
    const param = component.getParam(Number(args.paramIndex)); const actions = [];
    if (args.timeVarying !== undefined) actions.push(param.createSetTimeVaryingAction(!!args.timeVarying));
    const k = param.createKeyframe(args.value);
    if (args.timeSeconds !== undefined) k.position = tick(args.timeSeconds);
    if (args.addKeyframe) actions.push(param.createAddKeyframeAction(k));
    else actions.push(param.createSetValueAction(k, args.safeForPlayback !== false));
    const ok = p.executeTransaction(c => actions.forEach(a => c.addAction(a)), "Set effect parameter");
    if (!ok) throw new Error("Effect parameter transaction rejected"); return { ok: true };
  },

  async addVideoTransition(args) {
    const p = await activeProject(); const s = await sequenceByGuid(p, args.sequenceGuid);
    const { item } = await timelineItem(s, "video", args.trackIndex || 0, args.itemIndex || 0);
    const trans = ppro.TransitionFactory.createVideoTransition(args.matchName);
    const opts = new ppro.AddTransitionOptions()
      .setApplyToStart(args.position !== "end")
      .setDuration(tick(args.durationSeconds || 0.25))
      .setForceSingleSided(!!args.forceSingleSided)
      .setTransitionAlignment(Number(args.alignment || 0));
    transact(p, item.createAddVideoTransitionAction(trans, opts), "Add video transition"); return { ok: true };
  },

  async insertMogrt(args) {
    const p = await activeProject(); const s = await sequenceByGuid(p, args.sequenceGuid); const ed = ppro.SequenceEditor.getEditor(s);
    const items = args.path
      ? ed.insertMogrtFromPath(args.path, tick(args.timeSeconds), Number(args.videoTrackIndex || 0), Number(args.audioTrackIndex || 0))
      : ed.insertMogrtFromLibrary(args.libraryName, args.elementName, tick(args.timeSeconds), Number(args.videoTrackIndex || 0), Number(args.audioTrackIndex || 0));
    return { insertedCount: items.length };
  },

  async importAEComps(args) {
    const p = await activeProject(); const bin = await targetBin(p, args.targetBinId);
    const ok = args.compNames ? await p.importAEComps(args.aepPath, args.compNames, bin) : await p.importAllAEComps(args.aepPath, bin);
    return { imported: ok };
  },

  async exportFrame(args) {
    const p = await activeProject(); const s = await sequenceByGuid(p, args.sequenceGuid);
    return { exported: await ppro.Exporter.exportSequenceFrame(s, tick(args.timeSeconds), args.filename, args.filepath, Number(args.width), Number(args.height)) };
  },

  async exportSequence(args) {
    const p = await activeProject(); const s = await sequenceByGuid(p, args.sequenceGuid); const em = ppro.EncoderManager.getManager();
    let exportType = ppro.Constants.ExportType.IMMEDIATELY;
    if (args.queueToAME) exportType = ppro.Constants.ExportType.QUEUE_TO_AME;
    const ok = await em.exportSequence(s, exportType, args.outputFile || "", args.presetFile || "", args.exportFull !== false);
    return { exported: ok, ameInstalled: em.isAMEInstalled };
  },

  async exportTimelineInterchange(args) {
    const p = await activeProject(); const s = await sequenceByGuid(p, args.sequenceGuid);
    if (!ppro.ProjectConverter) throw new Error("ProjectConverter unavailable on this Premiere version");
    if (args.format === "otio" && ppro.ProjectConverter.exportAsOpenTimelineIO) return { exported: await ppro.ProjectConverter.exportAsOpenTimelineIO(s, args.path, args.suppressUI !== false) };
    if (args.format === "fcpxml" && ppro.ProjectConverter.exportAsFinalCutProXML) return { exported: await ppro.ProjectConverter.exportAsFinalCutProXML(s, args.path, args.suppressUI !== false) };
    if (args.format === "aaf" && ppro.ProjectConverter.exportAAF) return { exported: await ppro.ProjectConverter.exportAAF(s, args.path, args.options || {}) };
    throw new Error(`Unsupported interchange format/API: ${args.format}`);
  }
};

async function dispatch(message) {
  const { id, op, args } = message || {}; const handler = handlers[op];
  if (!handler) return { id, ok: false, error: `Unsupported bridge operation: ${op}` };
  try { return { id, ok: true, result: await handler(args || {}) }; }
  catch (e) { return { id, ok: false, error: e && e.message ? e.message : String(e), stack: e && e.stack ? e.stack : null }; }
}

function connect() {
  if (socket && (socket.readyState === 0 || socket.readyState === 1)) return;
  if (reconnectTimer) clearTimeout(reconnectTimer);
  setStatus(`Connecting to ${cfg.endpoint}…`);
  socket = new WebSocket(cfg.endpoint);
  socket.onopen = async () => {
    let caps = [];
    try { const c = await handlers.capabilities(); caps = Object.keys(c).filter(k => !!c[k]); } catch (_) {}
    setStatus(`Connected — Premiere ${host.version}, UXP ${versions.uxp}`);
    socket.send(JSON.stringify({ type: "hello", secret: cfg.secret, premiereVersion: host.version, uxpVersion: versions.uxp, bridgeVersion: cfg.bridgeVersion, capabilities: caps }));
  };
  socket.onmessage = async event => {
    let msg; try { msg = JSON.parse(event.data); } catch (_) { socket.send(JSON.stringify({ ok: false, error: "Invalid JSON" })); return; }
    socket.send(JSON.stringify(await dispatch(msg)));
  };
  socket.onerror = () => setStatus("Bridge connection error; retrying…");
  socket.onclose = () => { setStatus("Disconnected; retrying…"); reconnectTimer = setTimeout(connect, 1500); };
}
try {
  const { entrypoints } = require("uxp");
  entrypoints.setup({
    plugin: { create() { connect(); }, destroy() { try { if (socket) socket.close(); } catch (_) {} } },
    panels: {
      bridgePanel: {
        create() { connect(); },
        show() { connect(); }
      }
    }
  });
} catch (_) {}
connect();
