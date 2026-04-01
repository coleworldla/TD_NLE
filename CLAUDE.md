# CLAUDE.md — TD_NLE

## Project Overview

A TouchDesigner-native modular NLE / note sequencer. Not one giant patch — a data-driven player system where `.tox` files are clips, DAT tables are the edit decision list, and TD's native operators form the engine.

The editor should feel like Premiere or Resolume-style sequencing, but behave like a deterministic data-driven playback system under the hood.

## Core Architecture Principles

- `.tox` files = clips / scene modules
- DAT tables = single source of truth (never Panel positions)
- Reusable player pool loads and drives `.tox` clips
- Central transport resolves current time (frame-centric internally)
- Layer Mix TOP composites all active layers (single-pass shader)
- Timer CHOP / notes / automation add sequencing behavior
- Movie File Out TOP captures final output

## Repository Structure

```
TD_NLE/
├── model/
│   ├── clips_table              # Visual clips / .tox instances
│   ├── tracks_table             # Track metadata
│   ├── markers_table            # Manual and analyzed markers
│   ├── notes_table              # Note / trigger events
│   ├── automation_table         # Automation lanes
│   ├── transport_settings       # FPS, BPM, TC mode, offsets, loop points
│   └── analysis_table           # BPM, onsets, phrase suggestions, note candidates
├── transport/
│   ├── local/time               # Time COMP (component-local clock)
│   ├── timeline_master          # Timeline CHOP (transport readout)
│   ├── timecode_master          # Timecode CHOP (SMPTE-aware)
│   └── transport_resolve        # Resolves all clock modes to current frame
├── players/
│   ├── player_1                 # Reusable .tox player slot
│   ├── player_2
│   ├── player_3
│   └── player_4
├── mix/
│   ├── layermix_main            # Layer Mix TOP (final compositor)
│   ├── program_out              # Program output
│   └── record_out               # Record feed
├── audio/
│   ├── audiofilein1             # Audio File In CHOP
│   └── analysis                 # Offline audio analysis
├── ui/
│   ├── transport_bar            # Transport controls
│   ├── ruler_tc                 # SMPTE timecode ruler
│   ├── ruler_beats              # Beat/bar ruler
│   ├── track_headers            # Track header panel
│   ├── clip_canvas              # Clip block editor
│   ├── note_canvas              # Note/trigger lane editor
│   └── inspector                # Selected item properties
├── record/
│   ├── burnin_optional          # Timecode/metadata burn-in overlay
│   └── moviefileout1            # Movie File Out TOP
└── scripts/
    ├── extTransport             # Transport extension
    ├── extSequencer             # Sequencer/playback engine
    ├── extPlayerPool            # Player pool manager
    ├── extAnalysis              # Audio analysis pipeline
    └── extRecorder              # Record/export manager
```

## Subsystem Specifications

### 1. Model (DAT Tables)

DAT tables are the heart of the editor. Panel positions are never the truth.

**clips_table**
```
id | track | tox_path | subcomp | start_frame | duration_frames | start_tc | end_tc | in_offset | out_offset | opacity | blend_mode | transition_in | transition_out | preroll_frames | enabled | params_json
```

**tracks_table**
```
track | type | name | mute | solo | color | height
```

**notes_table**
```
id | lane | start_frame | duration_frames | start_tc | velocity | event_type | target | value | params_json
```

**markers_table**
```
frame | tc | kind | label | strength
```

**transport_settings**
```
clock_source | fps | tc_offset | bpm | signature_num | signature_den | loop_start_frame | loop_end_frame
```

**analysis_table**
```
frame | tc | beat | bar | onset_strength | phrase_id | note_guess | bpm_confidence
```

### 2. Transport

Four clock modes:
- **Internal edit time** — normal TD timeline
- **SMPTE timecode** — chase or generate
- **Beat/BPM-aware** — musical grid
- **Manual scrub/index** — direct frame control

**Key operators:**
- **Time COMP** — component-local clock, drives custom time-based systems
- **Timeline CHOP** — outputs frame, rate, start/end, range, BPM, signature, play state; supports Use Timecode mode
- **Timecode CHOP** — generates/parses TC from string, channels, timeline, index, OP, or Python object; SMPTE mode

**Timing rules:**
- Store all engine timing internally as frames
- Store timecode strings for display and manual editing
- Transport resolves to one current frame position
- Everything else compares against frames

**Cue behaviors:**
- Edit mode: normal internal time
- Timecode chase: playback follows incoming/generated SMPTE
- Hard chase: jump directly to correct local clip time
- Soft chase: enter right clip position, simplify transitions after jumps
- Pre-roll: load clip early so it is warm at start frame

### 3. Player Pool

A small pool of reusable players (not one live player per clip forever).

Each player must:
- Load an external `.tox` via path
- Optionally load a sub-component from that `.tox`
- Expose a standard clip interface
- Output one stable `OUT_TOP`
- Preload shortly before clip start time
- Unload or idle after clip end time

Uses TD's external `.tox` system with Load on Demand.

### 4. Layer Bus (Mix)

All active scene outputs feed into one **Layer Mix TOP**.

Capabilities used:
- True layer stacking (front-to-back or back-to-front)
- Per-layer: crop, fit, justify, scale, rotate, translate, pivot
- Per-layer: opacity, brightness, gamma, levels
- Per-layer: blend operation
- Supports both wired inputs and pattern-referenced TOPs
- Opacity = 0 optimizes cooking (layer skipped)
- One final output texture

### 5. Notes and Cues

A "note" means any timed event, not just MIDI:
- Scene launch
- Trigger pulse
- Transition
- Blend-mode change
- Parameter bump
- Camera cue
- OSC/MIDI/DMX action
- Rhythmic visual accent

**Timer CHOP** drives this via Segments DAT: begin/delay, length, serial/parallel timers, custom numeric columns become output channels.

### 6. Automation

Use **Animation COMP + Keyframe CHOP** (not a custom curve engine in v1).

Keyframe CHOP samples channel/key data from Animation COMP at a selectable sample rate, supports input as lookup index. Drives automation lanes for: opacity, transforms, color amount, glitch amount, camera values, etc.

### 7. Audio

Three jobs: playback, transport sync, analysis.

**Audio File In CHOP:**
- Streams from disk (few seconds in memory)
- Timeline-locked playback
- Explicit index playback (scrubbing)
- Timecode-object/CHOP/DAT driven playback

**Analysis strategy — offline-first:**
1. User loads audio file
2. Analysis runs once
3. Results cached into DATs
4. Timeline uses cached beat/onset/phrase/note suggestions

Optional backend: **EssentiaTD** (C++ CHOP plugins) for BPM estimation, beat tracking, onset detection, spectral descriptors, tonal features, loudness metrics.

### 8. Recorder

Separate subsystem: program_out, record_out, optional burn-in, time-sliced audio feed, Movie File Out TOP.

**Three record modes:**
- **Review:** fast codec, optional burn-in
- **Master:** higher-quality codec, clean image
- **Image sequence:** safest render path for finishing (TIFF/EXR)

Movie File Out TOP supports movie files, single images, image sequences, stop-frame, and embedded audio via time-sliced CHOP.

## Standard Clip Contract (.tox Modules)

Every timeline-ready `.tox` must expose this top-level interface:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `OUT_TOP` | TOP output | Yes | Final visual output |
| `Active` | toggle | Yes | Enable/disable cooking |
| `Localtime` | float | Yes | Current time within clip |
| `Clipprogress` | float | Yes | 0-1 normalized progress |
| `Opacity` | float | Yes | Master opacity |
| `Seed` | int | Yes | Randomization seed |
| `Palette` | menu/DAT | Yes | Color palette selector |
| `Bypassrender` | toggle | Yes | Skip rendering when hidden |
| `AudioReactive` | float | Optional | Audio reactivity amount |
| `BlendHint` | menu | Optional | Suggested blend mode |
| `Prewarm` | toggle | Optional | Pre-warm on load |

## Playback Rules

At current frame `f`, the sequencer must:

1. Resolve transport to `f`
2. Query active clips where `start_frame <= f < end_frame`
3. Assign those clips to available players
4. Compute each clip's `local_frame = f - start_frame`
5. Push `Localtime` / `Clipprogress` into the clip
6. Evaluate active notes at `f`
7. Sample automation at `f`
8. Send all active outputs into Layer Mix TOP
9. Feed final output to preview and recorder

## UI Design

Three synchronized views built with Panel Components + Container COMPs:

**Timeline View:** track headers, clip blocks, trim handles, transitions, SMPTE ruler, beat ruler, playhead, loop range

**Note View:** rhythmic lanes, beat/onset markers, trigger blocks, snap to beat/bar/marker/timecode

**Inspector View:** selected clip properties, selected note payload, blend mode, opacity, transform, .tox parameters

Use **Parameter Execute DAT** for editor-state changes (reacts to parameter changes without cooking the watched node).

## Phased Build Plan

### Phase 1 — Editorial Backbone
- DAT schemas (all tables)
- Transport system (Time COMP + Timeline CHOP + Timecode CHOP)
- Clip canvas (basic clip block rendering)
- Player pool (load/unload .tox, standard interface)
- Layer Mix TOP compositor
- Preview + record out

### Phase 2 — Music-Aware Sequencing
- Audio file lane (Audio File In CHOP)
- BPM/onset analysis (offline-first, optional EssentiaTD)
- Beat/bar ruler
- Note lanes + cue triggers
- Snap-to-beat/bar/marker

### Phase 3 — Automation and Show-Control Polish
- Animation COMP automation lanes
- SMPTE chase mode
- Pre-roll / hard chase / soft chase
- Burn-ins / naming / export presets

## TD Operator Reference

| Operator | Role |
|----------|------|
| Panel Components | Editor UI |
| Container COMP | UI layout building block |
| Time COMP | Component-local clock |
| Timeline CHOP | Transport readout (frame, rate, BPM, play state) |
| Timecode CHOP | SMPTE-aware transport |
| Timer CHOP | Segment/cue logic (DAT-driven) |
| Animation COMP | Automation lane storage |
| Keyframe CHOP | Automation lane sampling |
| Engine/COMP + .tox | Scene module loading (Load on Demand) |
| Layer Mix TOP | Final layered compositor (single-pass shader) |
| Audio File In CHOP | Timeline-aware audio playback/scrub |
| Movie File Out TOP | Recording/export |
| Parameter Execute DAT | Editor-state change reactions |

## Design Philosophy

Apply KISS, YAGNI, DRY, and SOLID principles. Prefer simple, elegant solutions. Think step by step whether a simpler approach exists before writing complex code. DAT tables are always the source of truth. The UI reflects the model, never the other way around.

## Reference Documentation

- Time COMP: https://docs.derivative.ca/Time_COMP
- Timeline CHOP: https://docs.derivative.ca/Timeline_CHOP
- Timecode CHOP: https://docs.derivative.ca/Timecode_CHOP
- Timer CHOP: https://docs.derivative.ca/Timer_CHOP
- Animation COMP: https://docs.derivative.ca/Animation_COMP
- Keyframe CHOP: https://docs.derivative.ca/Keyframe_CHOP
- Layer Mix TOP: https://docs.derivative.ca/Layer_Mix_TOP
- Audio File In CHOP: https://docs.derivative.ca/Audio_File_In_CHOP
- Movie File Out TOP: https://docs.derivative.ca/Movie_File_Out_TOP
- Panel Components: https://docs.derivative.ca/Panel_Component
- Write GLSL TOPs: https://derivative.ca/UserGuide/Write_a_GLSL_TOP
- External .tox: https://docs.derivative.ca/External_Tox
