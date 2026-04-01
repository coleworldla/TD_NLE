"""
timeline_ruler_callbacks - Ruler interaction helpers for TD_NLE.

These functions are intended to be called from the timeline_ruler panel's
callbacks DAT or button expressions.
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


def _utils():
    try:
        return mod.editor_state_utils
    except Exception:
        return None


def RulerState():
    utils = _utils()
    transport = _transport()
    if utils is None:
        return {}

    start_frame, end_frame = utils.visible_frame_range()
    playhead_frame = utils.read_int('playhead_frame', 0)
    hover_frame = utils.read_int('hover_frame', -1)
    loop_start, loop_end = (0, 0)
    loop_enabled = False
    fps = 30.0
    bpm = 120.0
    clock_source = 'internal'

    if transport is not None:
        loop_start, loop_end = transport.LoopRange
        loop_enabled = bool(transport.LoopEnabled)
        fps = float(transport.Fps)
        bpm = float(transport.Bpm)
        clock_source = transport.ClockSource

    return {
        'view_start_frame': start_frame,
        'view_end_frame': end_frame,
        'pixels_per_frame': utils.pixels_per_frame(),
        'playhead_frame': playhead_frame,
        'hover_frame': hover_frame,
        'loop_start_frame': loop_start,
        'loop_end_frame': loop_end,
        'loop_enabled': loop_enabled,
        'fps': fps,
        'bpm': bpm,
        'clock_source': clock_source,
    }


def BuildTickMarks(target_pixels=96, max_ticks=256):
    utils = _utils()
    transport = _transport()
    if utils is None:
        return []

    start_frame, end_frame = utils.visible_frame_range()
    approx_major = max(1.0, float(target_pixels) / utils.pixels_per_frame())
    major_step = utils.nice_frame_step(approx_major)
    minor_step = max(1, major_step // 5 if major_step >= 5 else 1)
    first_frame = (start_frame // minor_step) * minor_step

    ticks = []
    frame = first_frame
    while frame <= end_frame and len(ticks) < int(max_ticks):
        is_major = (frame % major_step) == 0
        ticks.append({
            'frame': frame,
            'x': utils.frame_to_x(frame),
            'major': is_major,
            'label': transport.FrameToTc(frame) if is_major and transport is not None else '',
        })
        frame += minor_step
    return ticks


def SetPlayheadFromX(x):
    utils = _utils()
    transport = _transport()
    if utils is None or transport is None:
        return None
    frame = utils.x_to_frame(x)
    transport.GoToFrame(frame)
    utils.write_state('playhead_frame', frame)
    return frame


def HoverFrameFromX(x):
    utils = _utils()
    if utils is None:
        return None
    frame = utils.x_to_frame(x)
    utils.write_state('hover_frame', frame)
    return frame


def WheelZoomAtX(x, wheel_steps):
    utils = _utils()
    if utils is None:
        return None
    return utils.zoom_about_x(x, wheel_steps)


def PanGesture(delta_x):
    utils = _utils()
    if utils is None:
        return None
    return utils.pan_by_pixels(-float(delta_x))


def HomeToFit():
    utils = _utils()
    if utils is None:
        return None
    return utils.home_to_fit()


def SyncPlayheadFromTransport():
    utils = _utils()
    if utils is None:
        return None
    return utils.sync_playhead_from_transport()