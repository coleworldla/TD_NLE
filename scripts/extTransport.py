"""
extTransport - Central transport engine for TD_NLE.

Attach to the /timeline_system COMP (or wherever the transport lives).
Reads transport_settings DAT for config. Resolves all clock modes
to a single current frame that drives the entire sequencer.

Operator references:
    transport_settings -> DAT  /timeline_system/model/transport_settings
    timeline_master    -> CHOP /timeline_system/transport/timeline_master
    timecode_master    -> CHOP /timeline_system/transport/timecode_master
    external_time_in   -> CHOP /timeline_system/transport/external_time_in
    local/time         -> COMP /timeline_system/transport/local/time
"""


class extTransport:

    def __init__(self, ownerComp):
        self.ownerComp = ownerComp
        self._settings = {}
        self._clock_source = 'internal'
        self._fps = 30.0
        self._bpm = 120.0
        self._sig_num = 4
        self._sig_den = 4
        self._loop_start = 0
        self._loop_end = 900
        self._loop_enabled = False
        self._tc_offset = '00:00:00:00'
        self._playing = False
        self._scrub_frame = 0
        self._external_seconds = 0.0
        self._external_seconds_offset = 0.0
        self.LoadSettings()

    @property
    def SettingsDAT(self):
        return self.ownerComp.op('model/transport_settings')

    @property
    def ExternalTimeCHOP(self):
        return self.ownerComp.op('transport/external_time_in')

    def LoadSettings(self):
        dat = self.SettingsDAT
        if dat is None or dat.numRows < 2:
            return
        self._settings = {}
        for row in range(1, dat.numRows):
            key = str(dat[row, 'key'])
            value = str(dat[row, 'value'])
            self._settings[key] = value
        self._clock_source = self._settings.get('clock_source', 'internal')
        self._fps = float(self._settings.get('fps', 30.0))
        self._bpm = float(self._settings.get('bpm', 120.0))
        self._sig_num = int(self._settings.get('signature_num', 4))
        self._sig_den = int(self._settings.get('signature_den', 4))
        self._loop_start = int(self._settings.get('loop_start_frame', 0))
        self._loop_end = int(self._settings.get('loop_end_frame', 900))
        self._loop_enabled = self._settings.get('loop_enabled', '0') == '1'
        self._tc_offset = self._settings.get('tc_offset', '00:00:00:00')
        self._external_seconds_offset = float(
            self._settings.get('external_seconds_offset', 0.0)
        )

    @property
    def Fps(self):
        return self._fps

    @property
    def Bpm(self):
        return self._bpm

    @property
    def BeatsPerFrame(self):
        return self._bpm / (60.0 * self._fps)

    @property
    def FramesPerBeat(self):
        return (60.0 * self._fps) / self._bpm

    @property
    def FramesPerBar(self):
        return self.FramesPerBeat * self._sig_num

    @property
    def ClockSource(self):
        return self._clock_source

    @property
    def Playing(self):
        return self._playing

    @property
    def LoopEnabled(self):
        return self._loop_enabled

    @property
    def LoopRange(self):
        return (self._loop_start, self._loop_end)

    def CurrentFrame(self):
        if self._clock_source == 'internal':
            return self._resolveInternal()
        if self._clock_source == 'external':
            return self._resolveExternal()
        if self._clock_source == 'timecode':
            return self._resolveTimecode()
        if self._clock_source == 'beat':
            return self._resolveBeat()
        if self._clock_source == 'scrub':
            return self._applyLoop(self._scrub_frame)
        return self._resolveInternal()

    def CurrentSeconds(self):
        return self.FrameToSeconds(self.CurrentFrame())

    def _resolveInternal(self):
        timeline = self.ownerComp.op('transport/timeline_master')
        if timeline is not None and timeline.numChans > 0:
            frame = int(timeline['frame'].eval())
            return self._applyLoop(frame)
        return self._applyLoop(int(absTime.frame))

    def _resolveExternal(self):
        external = self.ExternalTimeCHOP
        if external is not None and external.numChans > 0:
            self._external_seconds = self._readExternalSeconds(external)
        seconds = self._external_seconds + self._external_seconds_offset
        return self._applyLoop(self.SecondsToFrame(seconds))

    def _resolveTimecode(self):
        timecode = self.ownerComp.op('transport/timecode_master')
        if timecode is not None and timecode.numChans > 0:
            frame = int(timecode['index'].eval()) if 'index' in timecode else int(timecode[0].eval())
            frame += self._tcOffsetFrames()
            return self._applyLoop(frame)
        return self._resolveInternal()

    def _resolveBeat(self):
        return self._resolveInternal()

    def _readExternalSeconds(self, chop):
        for name in ('seconds', 'time', 'sec'):
            if name in chop:
                return float(chop[name].eval())
        if chop.numChans > 0:
            return float(chop[0].eval())
        return self._external_seconds

    def _applyLoop(self, frame):
        if not self._loop_enabled:
            return frame
        loop_length = self._loop_end - self._loop_start
        if loop_length <= 0:
            return frame
        if frame < self._loop_start:
            return frame
        if frame >= self._loop_end:
            return self._loop_start + ((frame - self._loop_start) % loop_length)
        return frame

    def _tcOffsetFrames(self):
        return self.TcToFrame(self._tc_offset)

    def FrameToTc(self, frame):
        fps = int(self._fps) if self._fps > 0 else 30
        total_seconds = int(frame // fps)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        frames = int(frame % fps)
        return '{:02d}:{:02d}:{:02d}:{:02d}'.format(hours, minutes, seconds, frames)

    def TcToFrame(self, tc_string):
        fps = int(self._fps) if self._fps > 0 else 30
        parts = tc_string.replace(';', ':').split(':')
        if len(parts) != 4:
            return 0
        hours, minutes, seconds, frames = [int(part) for part in parts]
        return ((hours * 3600 + minutes * 60 + seconds) * fps) + frames

    def FrameToSeconds(self, frame):
        fps = self._fps if self._fps > 0 else 30.0
        return float(frame) / fps

    def SecondsToFrame(self, seconds):
        fps = self._fps if self._fps > 0 else 30.0
        return int(round(float(seconds) * fps))

    def FrameToBeat(self, frame):
        return frame * self.BeatsPerFrame

    def BeatToFrame(self, beat):
        return int(round(beat * self.FramesPerBeat))

    def FrameToBar(self, frame):
        total_beats = self.FrameToBeat(frame)
        bar = int(total_beats // self._sig_num) + 1
        beat = (total_beats % self._sig_num) + 1
        return (bar, beat)

    def Play(self):
        self._playing = True
        time_comp = self.ownerComp.op('transport/local/time')
        if time_comp is not None:
            time_comp.par.play = True

    def Pause(self):
        self._playing = False
        time_comp = self.ownerComp.op('transport/local/time')
        if time_comp is not None:
            time_comp.par.play = False

    def Stop(self):
        self._playing = False
        time_comp = self.ownerComp.op('transport/local/time')
        if time_comp is not None:
            time_comp.par.play = False
            time_comp.par.rangestart = time_comp.par.start.eval()

    def GoToFrame(self, frame):
        frame = int(frame)
        self._scrub_frame = frame
        self._external_seconds = self.FrameToSeconds(frame)
        time_comp = self.ownerComp.op('transport/local/time')
        if time_comp is not None:
            time_comp.par.rangestart = frame
            time_comp.par.rangeend = time_comp.par.end.eval()

    def GoToTc(self, tc_string):
        self.GoToFrame(self.TcToFrame(tc_string))

    def GoToBeat(self, beat):
        self.GoToFrame(self.BeatToFrame(beat))

    def GoToBar(self, bar, beat=1):
        total_beats = (bar - 1) * self._sig_num + (beat - 1)
        self.GoToFrame(self.BeatToFrame(total_beats))

    def SetExternalTimeSeconds(self, seconds):
        self._external_seconds = float(seconds)

    def SetClockSource(self, source):
        if source in ('internal', 'external', 'timecode', 'beat', 'scrub'):
            self._clock_source = source
            self._writeSetting('clock_source', source)

    def SetBpm(self, bpm):
        bpm = max(1.0, float(bpm))
        self._bpm = bpm
        self._writeSetting('bpm', str(bpm))

    def SetLoop(self, start_frame, end_frame, enabled=True):
        self._loop_start = int(start_frame)
        self._loop_end = int(end_frame)
        self._loop_enabled = bool(enabled)
        self._writeSetting('loop_start_frame', str(self._loop_start))
        self._writeSetting('loop_end_frame', str(self._loop_end))
        self._writeSetting('loop_enabled', '1' if enabled else '0')

    def _writeSetting(self, key, value):
        dat = self.SettingsDAT
        if dat is None:
            return
        cell = dat[key, 'value']
        if cell is not None:
            cell.val = value
        else:
            dat.appendRow([key, value])
