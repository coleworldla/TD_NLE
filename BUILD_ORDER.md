# TD_NLE — Phased Node Build Order

Build in this order: modular scene timeline first, then notes, then automation, then timecode polish. Each phase ends with something testable.

---

## Phase 1: Modular Scene Timeline

Goal: Load .tox clips onto tracks, play them back on a timeline, composite via Layer Mix, and record. This is the usable MVP.

### Step 1.1 — Root structure

Create the root COMP `/timeline_system` with these child containers:

| Node | Type | Purpose |
|------|------|---------|
| `/timeline_system` | Base COMP | Root — attach all 6 extensions here |
| `/timeline_system/editor` | Base COMP | Panel-first timeline UI and editor state |
| `/timeline_system/model` | Base COMP | Holds all DAT tables |
| `/timeline_system/transport` | Base COMP | Clock subsystem |
| `/timeline_system/players` | Base COMP | Player pool |
| `/timeline_system/mix` | Base COMP | Compositor |
| `/timeline_system/audio` | Base COMP | Audio lane |
| `/timeline_system/record` | Base COMP | Export bus |
| `/timeline_system/scripts` | Base COMP | Extension scripts (Text DATs) |

**Action:** On `/timeline_system`, add all 6 extensions via the Extensions page:
- `extTransport` (promote to ext)
- `extPlayerPool` (promote to ext)
- `extSequencer` (promote to ext)
- `extAnalysis` (promote to ext)
- `extRecorder` (promote to ext)
- `extIngest` (promote to ext)

### Step 1.2 — Model DATs

Inside `/timeline_system/model`, create these Table DATs. Paste the headers from the `.txt` files in `model/`.

| Node | Type | Schema file |
|------|------|-------------|
| `clips_table` | Table DAT | model/clips_table.txt |
| `tracks_table` | Table DAT | model/tracks_table.txt |
| `markers_table` | Table DAT | model/markers_table.txt |
| `notes_table` | Table DAT | model/notes_table.txt |
| `automation_table` | Table DAT | model/automation_table.txt |
| `transport_settings` | Table DAT | model/transport_settings.txt |
| `analysis_table` | Table DAT | model/analysis_table.txt |

**Test:** Manually add a row to `clips_table` with a real `.tox` path. Confirm it shows up.


### Phase 0.5: Ingest + Editor Backbone

Goal: Add panel-first ingest and editor scaffolding before wiring the full playback network.

- Add `/timeline_system/editor` with `transport_bar`, `timeline_ruler`, `clip_canvas`, `note_canvas`, `automation_canvas`, `inspector`, `media_bin`, and an `editor_state` DAT.
- Add `/timeline_system/transport/external_time_in` and support `clock_source=external` where the public interface is seconds and the engine converts immediately to frames.
- Add `extIngest` for drag-and-drop `.tox`, video, and audio ingest with nondestructive `source_in`/`source_out` trim metadata.
- Split `/timeline_system/players` into `scene_players` and `media_players`; scene clips stay Engine-COMP-based while media clips are index-driven.
- Use `TD_NLE/scripts/clip_canvas_callbacks.py` as the canonical `clip_canvas` callbacks DAT; keep `dropzone_callbacks.py` as a file-drop-only compatibility wrapper.
- Add `editor/ui_theme`, `editor/material_icons`, `editor/transport_controls`, and `editor/glsl_panels` DATs so native panel chrome and selective GLSL overlays share one visual contract.
- Wire `editor_state_utils.py`, `transport_bar_actions.py`, and `timeline_ruler_callbacks.py` so zoom, pan, playhead drag, Home-to-fit, and selection all stay grounded in `editor_state`.
- Use `clip_canvas_callbacks.py` for hover, marquee/select helpers, clip move helpers, and drag/drop ingest on the same surface.

### Step 1.3 — Transport

Inside `/timeline_system/transport`:

| Node | Type | Config |
|------|------|--------|
| `local/time` | Time COMP | This is the master clock. Set Rate to match your FPS. |
| `timeline_master` | Timeline CHOP | Default settings. Outputs `frame`, `nframes`, `rate`, `play`, `fraction`. |
| `timecode_master` | Timecode CHOP | Input: `timeline_master`. Output: timecode channels. Set to SMPTE mode. |
| `external_time_in` | CHOP | External time input in seconds. Used when `clock_source=external`. |
| `transport_resolve` | CHOP Execute DAT | Calls `parent().ext.extSequencer.Tick()` on frame change. |

**Key wiring:**
- `timeline_master` references `local/time` as its Time component (or leave default for global time in Phase 1)
- `transport_resolve` watches `timeline_master` channel `frame` and fires `extSequencer.Tick()` each cook

**Test:** Hit play. Confirm `timeline_master` outputs incrementing frame values.

### Step 1.4 — Player pool

Inside `/timeline_system/players`:

| Node | Type | Config |
|------|------|--------|
| `player_1` | Base COMP | External .tox = (empty). Add custom pars: Active (Toggle), Localtime (Float), Clipprogress (Float 0-1), Opacity (Float 0-1), Seed (Int), Bypassrender (Toggle). |
| `player_2` | Base COMP | Clone of player_1 |
| `player_3` | Base COMP | Clone of player_1 |
| `player_4` | Base COMP | Clone of player_1 |

Inside each player, create a single `OUT_TOP` (Null TOP) that passes through whatever the loaded `.tox` outputs.

**Test:** Manually set `player_1`'s External .tox to a real `.tox` file. Confirm it loads and `OUT_TOP` shows output.

### Step 1.5 — Layer Mix compositor

Inside `/timeline_system/mix`:

| Node | Type | Config |
|------|------|--------|
| `layermix_main` | Layer Mix TOP | 4 inputs wired from player_1/OUT_TOP through player_4/OUT_TOP. Set all initial opacities to 0. Resolution = your target (1920x1080). |
| `program_out` | Null TOP | Input: `layermix_main`. This is your preview/program feed. |
| `record_out` | Null TOP | Input: `program_out` (or `burnin_optional` when active). Feed to recorder. |

**Key Layer Mix settings:**
- Extend: extend all layers to full resolution
- Operation Per Layer: Over (default)
- Each layer gets `Opacity0`, `Opacity1`, etc. — driven by `extSequencer`

**Test:** Manually set `Opacity0` to 1.0 on `layermix_main`. Confirm player_1's output appears in `program_out`.

### Step 1.6 — Record bus

Inside `/timeline_system/record`:

| Node | Type | Config |
|------|------|--------|
| `burnin_optional` | Text TOP or Base COMP | Overlays TC, frame, filename onto `program_out`. Active toggle. |
| `moviefileout1` | Movie File Out TOP | Input: `record_out`. File path, codec, record toggle driven by `extRecorder`. |

**Test:** Hit record via `parent().ext.extRecorder.StartRecord('review')`. Confirm file appears on disk.

### Step 1.7 — Wire the Tick loop

Create a **CHOP Execute DAT** (`transport_resolve`) that watches `timeline_master` and calls the sequencer:

```python
def onValueChange(channel, sampleIndex, val, prev):
    if channel.name == 'frame':
        parent().ext.extSequencer.Tick()
```

Or use a **Timer CHOP** in Repeat mode at your FPS to call `Tick()`.

**Phase 1 integration test:**
1. Add a row to `clips_table`: `id=1, track=0, tox_path=path/to/test.tox, start_frame=0, duration_frames=150, opacity=1, enabled=1`
2. Hit Play
3. Confirm: player_1 loads the tox, Layer Mix shows it, program_out displays it
4. Start recording, play through, stop recording
5. Confirm: exported file plays back correctly

---

## Phase 2: Notes and Cues

Goal: Add timed events that fire triggers, parameter changes, OSC, or scene launches on the beat grid.

### Step 2.1 — Timer CHOP for cue playback

Inside `/timeline_system/transport` (or a new `/timeline_system/cues` container):

| Node | Type | Config |
|------|------|--------|
| `timer_cues` | Timer CHOP | Segments DAT = a Table DAT built from `notes_table`. Callbacks drive `extSequencer._fireNote()`. |
| `notes_segments` | Table DAT | Generated by Python from `notes_table` — converts note rows into Timer CHOP segment format (begin, length, custom columns). |

The `extSequencer._evaluateNotes()` already queries `notes_table` directly per frame — this is the simpler path. Timer CHOP is the alternative if you want TD-native segment callbacks.

**Recommendation for Phase 2:** Use the Python path (`_evaluateNotes`) first. It's already written and frame-accurate. Add Timer CHOP later if you need hardware-timed precision.

### Step 2.2 — Note types to test

Add rows to `notes_table` with these event types:

| event_type | target | value | What it does |
|------------|--------|-------|--------------|
| `trigger` | `players/player_1` | | Pulses `Trigger` par on player |
| `par_set` | `players/player_1:Opacity` | `0.5` | Sets a parameter |
| `blend_mode` | `1` (clip id) | `add` | Changes clip blend mode |
| `scene_launch` | `2` (clip id) | | Enables a clip |

### Step 2.3 — Audio lane

Inside `/timeline_system/audio`:

| Node | Type | Config |
|------|------|--------|
| `audiofilein1` | Audio File In CHOP | File = your audio track. Play Mode = Locked to Timeline (for edit sync) or specify Index for scrubbing. |
| `audio_out` | Audio Device Out CHOP | Input: `audiofilein1`. For monitoring. |

**Test:** Play the timeline. Confirm audio plays in sync with clips.

### Step 2.4 — Analysis (EssentiaTD)

Inside `/timeline_system/audio/analysis`:

| Node | Type | Config |
|------|------|--------|
| `mono_sum` | Math CHOP | Input: `audiofilein1`. Combine CHOPs = Average. Outputs mono for analysis. |
| `essentia_rhythm` | Essentia Rhythm CHOP | Input: `mono_sum`. Mode = Batch. |
| `essentia_loudness` | Essentia Loudness CHOP | Input: `mono_sum`. Mode = Batch. |
| `essentia_tonal` | Essentia Tonal CHOP | Input: `mono_sum`. Mode = Batch. |
| `essentia_spectral` | Essentia Spectral CHOP | Input: `mono_sum`. Mode = Batch. |

If EssentiaTD is not installed, skip these — `extAnalysis` has a fallback path.

**Test:** Call `parent().ext.extAnalysis.Analyze()`. Check `analysis_table` and `markers_table` are populated.

**Phase 2 integration test:**
1. Load audio, run analysis
2. Add note rows for triggers at beat frames from `analysis_table`
3. Play timeline with audio + clips + notes
4. Confirm triggers fire at the right moments

---

## Phase 3: Automation

Goal: Keyframe-animated parameter curves for opacity, transforms, color, etc.

### Step 3.1 — Automation lane container

Inside `/timeline_system` add:

| Node | Type | Config |
|------|------|--------|
| `/timeline_system/automation` | Base COMP | Holds one Animation COMP + Keyframe CHOP per lane |

### Step 3.2 — Per-lane structure

For each row in `automation_table`, create dynamically (or pre-build a few):

| Node | Type | Config |
|------|------|--------|
| `lane_{id}` | Keyframe CHOP | Channel data from the lane's Animation COMP. Sample Rate = project FPS. |
| `anim_{id}` | Animation COMP | Stores the keyframe data. Channels match `target_par`. |

`extSequencer._sampleAutomation()` already reads `automation_table` and looks for `lane_{id}` Keyframe CHOPs.

### Step 3.3 — Automation targets to test

| target_path | target_par | Use case |
|-------------|------------|----------|
| `players/player_1` | `Opacity` | Fade in/out a clip |
| `mix/layermix_main` | `Translatex0` | Pan a layer |
| `mix/layermix_main` | `Scale0` | Zoom a layer |

**Phase 3 integration test:**
1. Add an automation lane: opacity ramp from 0 to 1 over 60 frames
2. Play timeline
3. Confirm the target parameter animates smoothly
4. Record and verify the animation is in the export

---

## Phase 4: Timecode Polish

Goal: SMPTE chase, pre-roll, hard/soft chase, burn-in metadata, export presets.

### Step 4.1 — Timecode chase

| Node | Change |
|------|--------|
| `timecode_master` | Set Source = Timecode String or External OP for incoming SMPTE |
| `transport_settings` | Set `clock_source` = `timecode` |

`extTransport._resolveTimecode()` already reads `timecode_master` and applies `tc_offset`.

### Step 4.2 — Pre-roll and chase behaviors

These are logic in `extPlayerPool`:
- **Pre-roll** already works via `preroll_frames` in `clips_table` and `PrerollClipsAtFrame()`
- **Hard chase:** When transport jumps > N frames, immediately snap all players to correct local time (already the default behavior in `_drivePlayer`)
- **Soft chase:** Add a lerp mode to `_drivePlayer` where `Localtime` eases to the target over a few frames after a jump. Add a `_chase_mode` flag to `extPlayerPool`.

### Step 4.3 — Burn-in polish

Enhance `burnin_optional`:
- Text TOP composited over `program_out`
- Fields: Timecode, Frame, Bar:Beat, Filename, Date, Record Mode
- `extRecorder.UpdateBurnin(frame)` pushes values each frame

### Step 4.4 — Export presets

Already built into `extRecorder.PRESETS`. To extend:
- Add a `presets_table` DAT for user-defined presets
- Add `ExportRange()` for non-realtime offline renders
- Add image sequence support (already in the preset dict)

**Phase 4 integration test:**
1. Set clock to timecode chase, send TC from a generator
2. Confirm playback follows incoming timecode
3. Record with burn-in enabled
4. Export same range as clean master
5. Verify both files

---

## Summary: What to build in TD vs. what's already scripted

| Component | Build in TD (nodes) | Already scripted (Python) |
|-----------|-------------------|--------------------------|
| Root COMP structure | Yes | — |
| DAT tables | Yes (paste headers) | Schemas provided |
| Time COMP + Timeline CHOP + Timecode CHOP | Yes | extTransport drives them |
| Engine COMPs (4x) with surfaced clip pars | Yes | extPlayerPool manages them |
| Layer Mix TOP + Null TOPs | Yes | extSequencer updates opacity/blend |
| Movie File Out TOP | Yes | extRecorder configures it |
| Audio File In CHOP | Yes | extAnalysis reads from it |
| EssentiaTD CHOPs (optional) | Yes (drop DLLs + create nodes) | extAnalysis triggers + harvests |
| Timer CHOP for cues (optional) | Yes | extSequencer handles notes via DAT |
| Animation COMP + Keyframe CHOP | Yes (per lane) | extSequencer samples them |
| CHOP Execute for Tick loop | Yes | 2-line callback |
| UI panels | Yes (Phase 2-3) | Extensions provide data |
| Burn-in overlay TOP | Yes | extRecorder pushes values |
