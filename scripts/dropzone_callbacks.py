"""
dropzone_callbacks - Compatibility wrapper for file-drop-only clip_canvas setups.

The canonical clip-canvas callback DAT is now clip_canvas_callbacks.py. This
module remains safe to wire directly if you only want drag-and-drop ingest.
"""

import os


def onDropItems(dropItems, baseName, x, y):
    try:
        return mod.clip_canvas_callbacks.onDropItems(dropItems, baseName, x, y)
    except Exception:
        pass

    ingest = _ingestExtension()
    if ingest is None:
        return
    canvas_height = getattr(parent(), 'height', 0)
    track = _trackFromY(y, canvas_height)
    start_frame = _startFrameFromX(x)
    for item in dropItems:
        path = _itemPath(item)
        if not path or not _isSupported(path, ingest):
            continue
        row_id = ingest.IngestFile(path=path, track=track, start_frame=start_frame)
        if row_id:
            start_frame += max(1, _durationForRow(row_id))


def _utils():
    try:
        return mod.editor_state_utils
    except Exception:
        return None


def _ingestExtension():
    timeline = op('/timeline_system')
    if timeline is None:
        return None
    return getattr(timeline.ext, 'extIngest', None)


def _itemPath(item):
    for attr in ('location', 'path', 'filePath'):
        if hasattr(item, attr):
            value = getattr(item, attr)
            if value:
                return str(value)
    return ''


def _isSupported(path, ingest):
    extension = os.path.splitext(path)[1].lower()
    return extension in ingest.ALL_SUPPORTED


def _trackFromY(y, canvas_height):
    utils = _utils()
    if utils is not None:
        return utils.track_from_y(y, canvas_height)

    tracks_dat = op('/timeline_system/model/tracks_table')
    if tracks_dat is None or tracks_dat.numRows < 2:
        return 0
    logical_y = max(0.0, float(canvas_height) - float(y))
    cursor = 0.0
    last_track = 0
    for row in range(1, tracks_dat.numRows):
        track = int(tracks_dat[row, 'track'])
        height = float(tracks_dat[row, 'height'] or 80)
        last_track = track
        if cursor <= logical_y < cursor + height:
            return track
        cursor += height
    return last_track


def _startFrameFromX(x):
    utils = _utils()
    if utils is not None:
        return utils.x_to_frame(x)

    pixels_per_frame = _editorStateFloat('pixels_per_frame', 2.0)
    view_start_frame = int(_editorStateFloat('view_start_frame', 0.0))
    pixels_per_frame = max(0.001, pixels_per_frame)
    return view_start_frame + int(float(x) / pixels_per_frame)


def _durationForRow(row_id):
    clips_dat = op('/timeline_system/model/clips_table')
    if clips_dat is None:
        return 0
    for row in range(1, clips_dat.numRows):
        if str(clips_dat[row, 'id']) == str(row_id):
            return int(clips_dat[row, 'duration_frames'])
    return 0


def _editorStateFloat(key, default):
    editor_state = op('/timeline_system/editor/editor_state')
    if editor_state is None:
        return float(default)
    cell = editor_state[key, 'value']
    if cell is None:
        return float(default)
    try:
        return float(cell.val)
    except Exception:
        return float(default)