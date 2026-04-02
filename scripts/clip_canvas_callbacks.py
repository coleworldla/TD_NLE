"""
clip_canvas_callbacks - Clip-canvas interaction helpers for TD_NLE.

Canonical callback module for /timeline_system/editor/clip_canvas. Keeps
selection and hover in editor_state and delegates ingest to extIngest.
"""

import os


def _timeline():
    try:
        return op('/timeline_system')
    except Exception:
        return None


def _utils():
    try:
        return mod.editor_state_utils
    except Exception:
        return None


def _ingest():
    timeline = _timeline()
    if timeline is None:
        return None
    return getattr(timeline.ext, 'extIngest', None)


def onDropItems(dropItems, baseName, x, y):
    ingest = _ingest()
    utils = _utils()
    if ingest is None or utils is None:
        return

    canvas_height = getattr(parent(), 'height', 0)
    track = utils.track_from_y(y, canvas_height)
    start_frame = utils.x_to_frame(x)

    for item in dropItems:
        path = _itemPath(item)
        if not path or not _isSupported(path, ingest):
            continue
        row_id = ingest.IngestFile(path=path, track=track, start_frame=start_frame)
        if row_id:
            rects = [rect for rect in utils.visible_clip_rects(canvas_height) if rect['id'] == str(row_id)]
            duration = rects[0]['duration_frames'] if rects else 1
            start_frame += max(1, int(duration))


def VisibleClipRects(canvas_height=0):
    utils = _utils()
    if utils is None:
        return []
    return utils.visible_clip_rects(canvas_height)


def OverlayState(canvas_height=0):
    utils = _utils()
    if utils is None:
        return {}
    return {
        'clips': utils.visible_clip_rects(canvas_height),
        'selected_clip_ids': utils.selected_clip_ids(),
        'hover_frame': utils.read_int('hover_frame', -1),
        'hover_track': utils.read_int('hover_track', -1),
        'hover_clip_id': utils.read_state('hover_clip_id', ''),
        'playhead_frame': utils.read_int('playhead_frame', 0),
    }


def UpdateHover(x, y, canvas_height=0):
    utils = _utils()
    if utils is None:
        return {}
    return utils.set_hover_from_panel(x, y, canvas_height)


def SelectAtPosition(x, y, canvas_height=0, mode='replace'):
    utils = _utils()
    if utils is None:
        return []
    return utils.select_clip_at_point(x, y, canvas_height, mode=mode)


def MarqueeSelect(start_x, start_y, end_x, end_y, canvas_height=0, mode='replace'):
    utils = _utils()
    if utils is None:
        return []
    return utils.marquee_select(start_x, start_y, end_x, end_y, canvas_height, mode=mode)


def MoveSelectedByDelta(delta_frames, delta_tracks=0):
    utils = _utils()
    if utils is None:
        return []
    return utils.move_selected_clips(delta_frames, delta_tracks)


def HomeToFit():
    utils = _utils()
    if utils is None:
        return None
    return utils.home_to_fit()


def BrowseTox(track=None, start_frame=None, shell_type='scene3d'):
    """Open a file picker for the given shell_type and ingest the result.

    Called by Browse buttons in the media bin UI. shell_type must be one of:
    'scene3d', 'scene2d', 'fx', 'video', 'audio'.
    """
    ingest = _ingest()
    utils = _utils()
    if ingest is None:
        return None
    if start_frame is None and utils is not None:
        start_frame = utils.read_int('hover_frame', 0)
    return ingest.BrowseAndIngest(track=track, start_frame=start_frame,
                                  shell_type=shell_type)


def ChangeShellType(clip_id, shell_type):
    """Change the shell_type of an existing clip — called from the inspector."""
    ingest = _ingest()
    if ingest is None:
        return False
    return ingest.SetClipShellType(clip_id, shell_type)


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