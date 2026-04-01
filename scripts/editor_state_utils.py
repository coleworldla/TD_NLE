"""
editor_state_utils - Shared editor-state helpers for TD_NLE UI.

These helpers keep viewport math, hover state, and clip selection grounded in
the editor_state DAT instead of panel-local state.
"""

import json
import math


DEFAULT_VIEW_START = 0
DEFAULT_VIEW_END = 900
DEFAULT_PIXELS_PER_FRAME = 2.0
DEFAULT_PADDING_FRAMES = 24
DEFAULT_SELECTION_MODE = 'replace'


def _root():
    try:
        return op('/timeline_system')
    except Exception:
        return None


def _op(relative_path):
    root = _root()
    if root is not None:
        try:
            found = root.op(relative_path)
            if found is not None:
                return found
        except Exception:
            pass
    try:
        return op('/timeline_system/' + relative_path)
    except Exception:
        return None


def editor_state_dat():
    return _op('editor/editor_state')


def clips_dat():
    return _op('model/clips_table')


def tracks_dat():
    return _op('model/tracks_table')


def transport():
    root = _root()
    if root is None:
        return None
    return getattr(root.ext, 'extTransport', None)


def _cell(dat, key, column='value'):
    if dat is None:
        return None
    try:
        return dat[key, column]
    except Exception:
        return None


def _cell_value(cell, default=''):
    if cell is None:
        return default
    try:
        value = cell.val
    except Exception:
        value = str(cell)
    return default if value in (None, '') else value


def read_state(key, default=''):
    return _cell_value(_cell(editor_state_dat(), key), default)


def read_float(key, default=0.0):
    try:
        return float(read_state(key, default))
    except Exception:
        return float(default)


def read_int(key, default=0):
    try:
        return int(round(float(read_state(key, default))))
    except Exception:
        return int(default)


def read_json_list(key):
    raw = str(read_state(key, '[]')).strip() or '[]'
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except Exception:
        pass
    return []


def write_state(key, value):
    dat = editor_state_dat()
    if dat is None:
        return False
    if isinstance(value, (list, dict, tuple)):
        text = json.dumps(value)
    else:
        text = str(value)
    cell = _cell(dat, key)
    if cell is not None:
        cell.val = text
    else:
        dat.appendRow([key, text])
    return True


def pixels_per_frame():
    return max(0.05, read_float('pixels_per_frame', DEFAULT_PIXELS_PER_FRAME))


def visible_frame_range():
    start = max(0, read_int('view_start_frame', DEFAULT_VIEW_START))
    end = max(start + 1, read_int('view_end_frame', DEFAULT_VIEW_END))
    return (start, end)


def panel_width_pixels():
    start, end = visible_frame_range()
    return max(1.0, float(end - start) * pixels_per_frame())


def set_view_range(start_frame, end_frame, pixels=None):
    start_frame = max(0, int(math.floor(float(start_frame))))
    end_frame = max(start_frame + 1, int(math.ceil(float(end_frame))))
    write_state('view_start_frame', start_frame)
    write_state('view_end_frame', end_frame)
    if pixels is not None:
        write_state('pixels_per_frame', max(0.05, float(pixels)))
    return (start_frame, end_frame)


def frame_to_x(frame):
    start, _ = visible_frame_range()
    return (float(frame) - float(start)) * pixels_per_frame()


def x_to_frame(x):
    start, _ = visible_frame_range()
    return max(0, int(math.floor(float(start) + (float(x) / pixels_per_frame()))))


def selected_clip_ids():
    return read_json_list('selected_clip_ids')


def set_selected_clip_ids(ids, mode=DEFAULT_SELECTION_MODE):
    incoming = [str(item) for item in ids if str(item)]
    current = selected_clip_ids()

    if mode == 'add':
        merged = current + [item for item in incoming if item not in current]
    elif mode == 'toggle':
        merged = list(current)
        for item in incoming:
            if item in merged:
                merged.remove(item)
            else:
                merged.append(item)
    else:
        merged = incoming

    write_state('selected_clip_ids', merged)
    return merged


def clear_clip_selection():
    return set_selected_clip_ids([], mode='replace')


def track_rows():
    dat = tracks_dat()
    if dat is None or dat.numRows < 2:
        return [{'track': 0, 'height': 80.0, 'name': 'Track 1'}]

    rows = []
    for row in range(1, dat.numRows):
        try:
            track = int(dat[row, 'track'])
        except Exception:
            track = row - 1
        try:
            height = float(dat[row, 'height'] or 80)
        except Exception:
            height = 80.0
        try:
            name = str(dat[row, 'name'])
        except Exception:
            name = 'Track {}'.format(track + 1)
        rows.append({
            'track': track,
            'height': max(1.0, height),
            'name': name,
        })
    return rows or [{'track': 0, 'height': 80.0, 'name': 'Track 1'}]


def total_track_height():
    return sum(row['height'] for row in track_rows())


def track_from_y(y, canvas_height=None):
    rows = track_rows()
    canvas_height = float(canvas_height if canvas_height not in (None, 0, '') else total_track_height())
    logical_y = max(0.0, canvas_height - float(y))
    cursor = 0.0
    last_track = rows[-1]['track']
    for row in rows:
        if cursor <= logical_y < cursor + row['height']:
            return row['track']
        cursor += row['height']
    return last_track


def _track_layout(canvas_height=None):
    rows = track_rows()
    canvas_height = float(canvas_height if canvas_height not in (None, 0, '') else total_track_height())
    layout = {}
    top_cursor = 0.0
    for row in rows:
        height = row['height']
        layout[row['track']] = {
            'track': row['track'],
            'height': height,
            'top': top_cursor,
            'bottom': canvas_height - top_cursor - height,
        }
        top_cursor += height
    return layout


def _table_rows(dat):
    if dat is None or dat.numRows < 2:
        return []
    headers = [str(dat[0, col]) for col in range(dat.numCols)]
    rows = []
    for row in range(1, dat.numRows):
        item = {}
        for col, header in enumerate(headers):
            item[header] = str(dat[row, col])
        rows.append(item)
    return rows


def clip_rows(include_disabled=False):
    rows = []
    for item in _table_rows(clips_dat()):
        if not include_disabled and item.get('enabled', '1') == '0':
            continue
        rows.append(item)
    return rows


def visible_clip_rects(canvas_height=None):
    layout = _track_layout(canvas_height)
    selected = set(selected_clip_ids())
    rects = []
    for clip in clip_rows():
        track = int(clip.get('track', 0) or 0)
        track_box = layout.get(track)
        if track_box is None:
            continue
        start_frame = int(clip.get('start_frame', 0) or 0)
        duration = max(1, int(clip.get('duration_frames', 1) or 1))
        end_frame = start_frame + duration
        x = frame_to_x(start_frame)
        width = max(1.0, frame_to_x(end_frame) - x)
        rects.append({
            'id': str(clip.get('id', '')),
            'track': track,
            'x': x,
            'y': track_box['bottom'],
            'w': width,
            'h': track_box['height'],
            'selected': str(clip.get('id', '')) in selected,
            'media_type': clip.get('media_type', 'tox'),
            'label': clip.get('preset_name', '') or clip.get('template_path', '').split('/')[-1].split('\\')[-1],
            'start_frame': start_frame,
            'duration_frames': duration,
        })
    return rects


def clip_at_point(x, y, canvas_height=None):
    x = float(x)
    y = float(y)
    for rect in reversed(visible_clip_rects(canvas_height)):
        if rect['x'] <= x <= (rect['x'] + rect['w']) and rect['y'] <= y <= (rect['y'] + rect['h']):
            return rect
    return None


def set_hover_from_panel(x, y, canvas_height=None):
    hover_frame = x_to_frame(x)
    hover_track = track_from_y(y, canvas_height)
    clip = clip_at_point(x, y, canvas_height)
    hover_clip_id = clip['id'] if clip is not None else ''
    write_state('hover_frame', hover_frame)
    write_state('hover_track', hover_track)
    write_state('hover_clip_id', hover_clip_id)
    return {
        'hover_frame': hover_frame,
        'hover_track': hover_track,
        'hover_clip_id': hover_clip_id,
    }


def select_clip_at_point(x, y, canvas_height=None, mode=DEFAULT_SELECTION_MODE):
    clip = clip_at_point(x, y, canvas_height)
    if clip is None:
        if mode == 'replace':
            clear_clip_selection()
        return []
    return set_selected_clip_ids([clip['id']], mode=mode)


def marquee_select(start_x, start_y, end_x, end_y, canvas_height=None, mode=DEFAULT_SELECTION_MODE):
    x0 = min(float(start_x), float(end_x))
    x1 = max(float(start_x), float(end_x))
    y0 = min(float(start_y), float(end_y))
    y1 = max(float(start_y), float(end_y))
    hits = []
    for rect in visible_clip_rects(canvas_height):
        intersects = not (
            rect['x'] + rect['w'] < x0 or
            rect['x'] > x1 or
            rect['y'] + rect['h'] < y0 or
            rect['y'] > y1
        )
        if intersects:
            hits.append(rect['id'])
    return set_selected_clip_ids(hits, mode=mode)


def sync_playhead_from_transport():
    ext_transport = transport()
    if ext_transport is None:
        return read_int('playhead_frame', 0)
    frame = int(ext_transport.CurrentFrame())
    write_state('playhead_frame', frame)
    return frame


def home_to_fit(padding_frames=DEFAULT_PADDING_FRAMES):
    clips = clip_rows()
    if not clips:
        return set_view_range(DEFAULT_VIEW_START, DEFAULT_VIEW_END, DEFAULT_PIXELS_PER_FRAME)

    current_width = panel_width_pixels()
    min_frame = min(int(clip.get('start_frame', 0) or 0) for clip in clips)
    max_frame = max(
        int(clip.get('start_frame', 0) or 0) + max(1, int(clip.get('duration_frames', 1) or 1))
        for clip in clips
    )
    start = max(0, min_frame - int(padding_frames))
    end = max(start + 1, max_frame + int(padding_frames))
    span = max(1.0, float(end - start))
    new_ppf = max(0.05, min(64.0, current_width / span))
    return set_view_range(start, end, new_ppf)


def zoom_about_x(x, wheel_steps, zoom_ratio=1.15):
    start, end = visible_frame_range()
    old_ppf = pixels_per_frame()
    width = max(1.0, float(end - start) * old_ppf)
    anchor_frame = float(start) + (float(x) / old_ppf)
    new_ppf = old_ppf * (float(zoom_ratio) ** float(wheel_steps))
    new_ppf = max(0.05, min(64.0, new_ppf))
    new_span = max(1.0, width / new_ppf)
    new_start = max(0.0, anchor_frame - (float(x) / new_ppf))
    new_end = new_start + new_span
    return set_view_range(new_start, new_end, new_ppf)


def pan_by_pixels(delta_x):
    start, end = visible_frame_range()
    span = end - start
    delta_frames = int(round(float(delta_x) / pixels_per_frame()))
    new_start = start + delta_frames
    if new_start < 0:
        new_start = 0
    return set_view_range(new_start, new_start + span)


def _clip_row_index(clip_id):
    dat = clips_dat()
    if dat is None or dat.numRows < 2:
        return None
    for row in range(1, dat.numRows):
        if str(dat[row, 'id']) == str(clip_id):
            return row
    return None


def _track_range():
    rows = track_rows()
    tracks = [row['track'] for row in rows]
    return (min(tracks), max(tracks))


def move_selected_clips(delta_frames, delta_tracks=0):
    dat = clips_dat()
    ext_transport = transport()
    if dat is None:
        return []

    min_track, max_track = _track_range()
    moved = []
    for clip_id in selected_clip_ids():
        row = _clip_row_index(clip_id)
        if row is None:
            continue
        start_frame = max(0, int(dat[row, 'start_frame']) + int(delta_frames))
        duration = max(1, int(dat[row, 'duration_frames'] or 1))
        track = int(dat[row, 'track'] or 0) + int(delta_tracks)
        track = max(min_track, min(max_track, track))

        dat[row, 'start_frame'] = str(start_frame)
        dat[row, 'track'] = str(track)
        if ext_transport is not None:
            try:
                dat[row, 'start_tc'] = ext_transport.FrameToTc(start_frame)
            except Exception:
                pass
            try:
                dat[row, 'end_tc'] = ext_transport.FrameToTc(start_frame + duration)
            except Exception:
                pass
        moved.append(str(clip_id))
    return moved


def nice_frame_step(target_frames):
    target_frames = max(1.0, float(target_frames))
    magnitude = 10 ** math.floor(math.log10(target_frames))
    for step in (1, 2, 5, 10):
        candidate = step * magnitude
        if target_frames <= candidate:
            return int(candidate)
    return int(10 * magnitude)