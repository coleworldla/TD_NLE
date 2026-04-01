"""
extRecorder — Record/export manager for TD_NLE.

Manages the Movie File Out TOP for capturing the final program output.
Supports three record modes:
    - Review:   fast codec, optional burn-in overlay
    - Master:   high-quality codec, clean image
    - Sequence: image sequence (TIFF/EXR) for finishing

Operator references:
    Program_out     -> TOP  /timeline_system/mix/program_out
    Record_out      -> TOP  /timeline_system/mix/record_out
    Burnin          -> TOP  /timeline_system/record/burnin_optional
    Moviefileout    -> TOP  /timeline_system/record/moviefileout1
    Audio_file_in   -> CHOP /timeline_system/audio/audiofilein1
"""

import os
import datetime


class extRecorder:

    def __init__(self, ownerComp):
        self.ownerComp = ownerComp
        self._recording = False
        self._mode = 'review'  # 'review', 'master', 'sequence'
        self._output_dir = ''
        self._filename_base = ''
        self._burnin_enabled = False

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def ProgramOut(self):
        return self.ownerComp.op('mix/program_out')

    @property
    def RecordOut(self):
        return self.ownerComp.op('mix/record_out')

    @property
    def BurninTOP(self):
        return self.ownerComp.op('record/burnin_optional')

    @property
    def MovieFileOut(self):
        return self.ownerComp.op('record/moviefileout1')

    @property
    def AudioSource(self):
        return self.ownerComp.op('audio/audio_mix') or self.ownerComp.op('audio/audiofilein1')

    @property
    def IsRecording(self):
        return self._recording

    @property
    def Mode(self):
        return self._mode

    # ------------------------------------------------------------------
    # Mode presets
    # ------------------------------------------------------------------

    # Codec / format settings per mode. These map to Movie File Out TOP pars.
    PRESETS = {
        'review': {
            'type': 'Movie',
            'videocodec': 'H.264',
            'imageformat': '',
            'quality': 0.7,
            'burnin': True,
        },
        'master': {
            'type': 'Movie',
            'videocodec': 'H.265',
            'imageformat': '',
            'quality': 0.95,
            'burnin': False,
        },
        'sequence': {
            'type': 'Image',
            'videocodec': '',
            'imageformat': 'TIFF',
            'quality': 1.0,
            'burnin': False,
        },
    }

    def SetMode(self, mode):
        """Set record mode: 'review', 'master', or 'sequence'."""
        if mode in self.PRESETS:
            self._mode = mode
            self._burnin_enabled = self.PRESETS[mode]['burnin']

    # ------------------------------------------------------------------
    # Output path
    # ------------------------------------------------------------------

    def SetOutputDir(self, path):
        self._output_dir = path

    def SetFilenameBase(self, name):
        self._filename_base = name

    def _resolveOutputPath(self):
        """Build the full output file path with timestamp."""
        base_dir = self._output_dir or project.folder + '/exports'
        base_name = self._filename_base or 'td_nle_export'
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        preset = self.PRESETS[self._mode]

        if preset['type'] == 'Image':
            # Image sequence: directory with numbered frames
            seq_dir = '{}/{}_{}'.format(base_dir, base_name, timestamp)
            return seq_dir + '/' + base_name + '.$F4.' + preset['imageformat'].lower()
        else:
            ext = 'mp4' if 'H.26' in preset.get('videocodec', '') else 'mov'
            return '{}/{}_{}.{}'.format(base_dir, base_name, timestamp, ext)

    # ------------------------------------------------------------------
    # Recording controls
    # ------------------------------------------------------------------

    def StartRecord(self, mode=None):
        """Begin recording with the specified mode (or current mode)."""
        if self._recording:
            debug('extRecorder: already recording')
            return
        if mode:
            self.SetMode(mode)

        mfo = self.MovieFileOut
        if mfo is None:
            debug('extRecorder: Movie File Out TOP not found')
            return

        preset = self.PRESETS[self._mode]
        output_path = self._resolveOutputPath()

        # Ensure output directory exists
        out_dir = os.path.dirname(output_path)
        if not os.path.exists(out_dir):
            os.makedirs(out_dir)

        # Configure Movie File Out
        mfo.par.file = output_path

        if preset['type'] == 'Movie':
            mfo.par.type = 'Movie'
            if hasattr(mfo.par, 'videocodec'):
                mfo.par.videocodec = preset['videocodec']
        elif preset['type'] == 'Image':
            mfo.par.type = 'Image'
            if hasattr(mfo.par, 'imageformat'):
                mfo.par.imageformat = preset['imageformat']

        # Wire burn-in or clean source
        self._configureBurnin(preset['burnin'])

        # Audio source (time-sliced CHOP for embedded audio)
        audio = self.AudioSource
        if audio is not None and preset['type'] == 'Movie':
            if hasattr(mfo.par, 'audiochop'):
                mfo.par.audiochop = audio.path

        # Start recording
        mfo.par.record = True
        self._recording = True
        debug('extRecorder: recording started — {} mode -> {}'.format(
            self._mode, output_path))

    def StopRecord(self):
        """Stop recording."""
        mfo = self.MovieFileOut
        if mfo is not None:
            mfo.par.record = False
        self._recording = False
        debug('extRecorder: recording stopped')

    def ToggleRecord(self, mode=None):
        if self._recording:
            self.StopRecord()
        else:
            self.StartRecord(mode)

    # ------------------------------------------------------------------
    # Burn-in
    # ------------------------------------------------------------------

    def _configureBurnin(self, enabled):
        """Route either the burn-in overlay TOP or the clean program_out
        into the Movie File Out TOP's input."""
        self._burnin_enabled = enabled
        burnin = self.BurninTOP
        record_out = self.RecordOut
        program_out = self.ProgramOut

        # The actual TOP wiring is done in the TD network.
        # Here we control whether the burn-in COMP is active.
        if burnin is not None:
            if hasattr(burnin.par, 'Active'):
                burnin.par.Active = enabled
            if hasattr(burnin.par, 'Bypassrender'):
                burnin.par.Bypassrender = not enabled

    def SetBurninEnabled(self, enabled):
        self._burnin_enabled = enabled
        self._configureBurnin(enabled)

    # ------------------------------------------------------------------
    # Burn-in content update (call per frame if burn-in is active)
    # ------------------------------------------------------------------

    def UpdateBurnin(self, frame):
        """Push current transport info into the burn-in overlay.
        The burn-in TOP should have Text TOPs or custom pars for:
        Timecode, Frame, Filename, Date, Mode."""
        if not self._burnin_enabled:
            return
        burnin = self.BurninTOP
        if burnin is None:
            return

        transport = self.ownerComp.ext.extTransport
        tc = transport.FrameToTc(frame) if transport else ''
        bar, beat = transport.FrameToBar(frame) if transport else (0, 0)

        if hasattr(burnin.par, 'Timecode'):
            burnin.par.Timecode = tc
        if hasattr(burnin.par, 'Frame'):
            burnin.par.Frame = frame
        if hasattr(burnin.par, 'Barbeat'):
            burnin.par.Barbeat = '{}:{}'.format(bar, beat)
        if hasattr(burnin.par, 'Filename'):
            burnin.par.Filename = self._filename_base or 'untitled'
        if hasattr(burnin.par, 'Recorddate'):
            burnin.par.Recorddate = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

    # ------------------------------------------------------------------
    # Quick export (non-realtime render)
    # ------------------------------------------------------------------

    def ExportRange(self, start_frame, end_frame, mode='master'):
        """Non-realtime export of a frame range. Drives transport frame
        by frame and records each. Best for offline master renders."""
        self.SetMode(mode)
        transport = self.ownerComp.ext.extTransport
        sequencer = self.ownerComp.ext.extSequencer

        self.StartRecord()
        for f in range(start_frame, end_frame + 1):
            transport.GoToFrame(f)
            sequencer.Tick()
            if self._burnin_enabled:
                self.UpdateBurnin(f)
            # Force cook the network for this frame
            self.MovieFileOut.cook(force=True)
        self.StopRecord()
        debug('extRecorder: export complete — frames {} to {}'.format(
            start_frame, end_frame))
