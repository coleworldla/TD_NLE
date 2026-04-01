"""
transport_bar_actions - Transport-bar action helpers for TD_NLE.

Designed for button callbacks or parameter expressions on /timeline_system/editor/transport_bar.
"""


def _timeline():
    try:
        return op('/timeline_system')
    except Exception:
        return None


def _transport():
    timeline = _timeline()
    if timeline is None:
        return None
    return getattr(timeline.ext, 'extTransport', None)


def _recorder():
    timeline = _timeline()
    if timeline is None:
        return None
    return getattr(timeline.ext, 'extRecorder', None)


def _utils():
    try:
        return mod.editor_state_utils
    except Exception:
        return None


def _editor_dat(name):
    timeline = _timeline()
    if timeline is None:
        return None
    return timeline.op('editor/{}'.format(name))


def _rows(dat, key_column):
    if dat is None or dat.numRows < 2:
        return []
    headers = [str(dat[0, col]) for col in range(dat.numCols)]
    rows = []
    for row in range(1, dat.numRows):
        item = {}
        for col, header in enumerate(headers):
            item[header] = str(dat[row, col])
        item['_key'] = item.get(key_column, '')
        rows.append(item)
    return rows


def _icon_row(semantic):
    for row in _rows(_editor_dat('material_icons'), 'semantic'):
        if row.get('semantic') == semantic:
            return row
    return {}


def ButtonRows():
    return _rows(_editor_dat('transport_controls'), 'action')


def IconName(semantic):
    return _icon_row(semantic).get('icon_name', '')


def Label(semantic):
    row = _icon_row(semantic)
    return row.get('label', semantic.replace('_', ' ').title())


def ReadoutData():
    transport = _transport()
    recorder = _recorder()
    if transport is None:
        return {
            'frame': 0,
            'tc': '00:00:00:00',
            'bpm': 120.0,
            'clock_source': 'internal',
            'playing': False,
            'recording': False,
            'record_mode': 'review',
            'loop_enabled': False,
        }

    frame = int(transport.CurrentFrame())
    return {
        'frame': frame,
        'tc': transport.FrameToTc(frame),
        'bpm': float(transport.Bpm),
        'clock_source': transport.ClockSource,
        'playing': bool(transport.Playing),
        'recording': bool(recorder.IsRecording) if recorder is not None else False,
        'record_mode': recorder.Mode if recorder is not None else 'review',
        'loop_enabled': bool(transport.LoopEnabled),
    }


def RunAction(action):
    transport = _transport()
    recorder = _recorder()
    utils = _utils()
    if transport is None:
        return None

    action = str(action)
    if action == 'play_toggle':
        if transport.Playing:
            transport.Pause()
        else:
            transport.Play()
    elif action == 'stop':
        transport.Stop()
    elif action == 'record_toggle':
        if recorder is not None:
            recorder.ToggleRecord(recorder.Mode or 'review')
    elif action == 'set_mode_review':
        if recorder is not None:
            recorder.SetMode('review')
    elif action == 'set_mode_master':
        if recorder is not None:
            recorder.SetMode('master')
    elif action == 'set_mode_sequence':
        if recorder is not None:
            recorder.SetMode('sequence')
    elif action == 'zoom_in' and utils is not None:
        utils.zoom_about_x(utils.panel_width_pixels() * 0.5, 1)
    elif action == 'zoom_out' and utils is not None:
        utils.zoom_about_x(utils.panel_width_pixels() * 0.5, -1)
    elif action == 'home_to_fit' and utils is not None:
        utils.home_to_fit()
    elif action == 'loop_toggle':
        start_frame, end_frame = transport.LoopRange
        if utils is not None and (end_frame - start_frame) <= 0:
            start_frame, end_frame = utils.visible_frame_range()
        transport.SetLoop(start_frame, end_frame, enabled=not transport.LoopEnabled)
    elif action == 'clock_internal':
        transport.SetClockSource('internal')
    elif action == 'clock_external':
        transport.SetClockSource('external')
    elif action == 'clock_timecode':
        transport.SetClockSource('timecode')
    else:
        return None

    if utils is not None:
        utils.sync_playhead_from_transport()
    return ReadoutData()