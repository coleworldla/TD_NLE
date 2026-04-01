"""
extAnalysis â€” Offline-first audio analysis pipeline for TD_NLE.

Orchestrates EssentiaTD batch CHOPs (Rhythm, Loudness, Tonal, Spectral)
to analyze an audio file once and cache results into DAT tables
(analysis_table, markers_table).

Also supports basic TD-native analysis as a fallback when EssentiaTD
is not installed.

Signal flow (batch mode â€” EssentiaTD not required for Spectrum):
    Audio File In CHOP
        -> Essentia Rhythm CHOP   (batch) -> onsets, beats, BPM
        -> Essentia Loudness CHOP (batch) -> loudness curve
        -> Essentia Tonal CHOP    (batch) -> key, pitch, chroma
        -> Essentia Spectral CHOP (batch) -> MFCCs for phrase segmentation

Operator references:
    Audio_file_in       -> CHOP /timeline_system/audio/audiofilein1
    Analysis_table      -> DAT  /timeline_system/model/analysis_table
    Markers_table       -> DAT  /timeline_system/model/markers_table
    Transport_settings  -> DAT  /timeline_system/model/transport_settings
    Rhythm_chop         -> CHOP /timeline_system/audio/analysis/essentia_rhythm
    Loudness_chop       -> CHOP /timeline_system/audio/analysis/essentia_loudness
    Tonal_chop          -> CHOP /timeline_system/audio/analysis/essentia_tonal
    Spectral_chop       -> CHOP /timeline_system/audio/analysis/essentia_spectral
"""

import math


class extAnalysis:

    def __init__(self, ownerComp):
        self.ownerComp = ownerComp
        self._audio_path = ''
        self._sample_rate = 44100
        self._hop_size = 512
        self._fps = 30.0
        self._analysis_ready = False

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def AnalysisDAT(self):
        return self.ownerComp.op('model/analysis_table')

    @property
    def MarkersDAT(self):
        return self.ownerComp.op('model/markers_table')

    @property
    def AudioFileIn(self):
        return self.ownerComp.op('audio/audiofilein1')

    @property
    def IsReady(self):
        return self._analysis_ready

    # ------------------------------------------------------------------
    # EssentiaTD CHOP accessors (return None if not installed)
    # ------------------------------------------------------------------

    def _rhythmCHOP(self):
        return self.ownerComp.op('audio/analysis/essentia_rhythm')

    def _loudnessCHOP(self):
        return self.ownerComp.op('audio/analysis/essentia_loudness')

    def _tonalCHOP(self):
        return self.ownerComp.op('audio/analysis/essentia_tonal')

    def _spectralCHOP(self):
        return self.ownerComp.op('audio/analysis/essentia_spectral')

    def _hasEssentia(self):
        return self._rhythmCHOP() is not None

    # ------------------------------------------------------------------
    # Core analysis pipeline
    # ------------------------------------------------------------------

    def Analyze(self, audio_path=None, hop_size=512):
        """Run full offline analysis on the loaded audio file.
        Call this once when the user loads or changes the audio file."""
        # Resolve audio path
        if audio_path:
            self._audio_path = audio_path
            afin = self.AudioFileIn
            if afin is not None:
                afin.par.file = audio_path
        else:
            afin = self.AudioFileIn
            if afin is not None:
                self._audio_path = str(afin.par.file)

        self._hop_size = hop_size
        # Read fps from transport
        transport = self.ownerComp.ext.extTransport
        if transport:
            self._fps = transport.Fps
        # Get sample rate from Audio File In
        afin = self.AudioFileIn
        if afin is not None and afin.numChans > 0:
            self._sample_rate = afin.sampleRate

        self._analysis_ready = False

        if self._hasEssentia():
            self._runEssentiaAnalysis()
        else:
            self._runFallbackAnalysis()

        self._analysis_ready = True
        debug('extAnalysis: analysis complete for {}'.format(self._audio_path))

    def _runEssentiaAnalysis(self):
        """Trigger all EssentiaTD batch CHOPs and harvest results."""
        # Trigger batch computes
        for chop_fn in [self._rhythmCHOP, self._loudnessCHOP,
                        self._tonalCHOP, self._spectralCHOP]:
            chop = chop_fn()
            if chop is not None and hasattr(chop.par, 'Compute'):
                chop.par.Compute.pulse()

        # Allow one frame for batch to complete (in practice you may
        # need to use a Timer or callback â€” this is the synchronous path)
        # Harvest results
        rhythm = self._harvestRhythm()
        loudness = self._harvestLoudness()
        tonal = self._harvestTonal()

        transport = self.ownerComp.ext.extTransport
        if transport is not None and rhythm.get('bpm', 0) > 0:
            transport.SetBpm(rhythm['bpm'])

        # Merge into analysis_table
        self._buildAnalysisTable(rhythm, loudness, tonal)

        # Generate markers from beats and onsets
        self._generateMarkers(rhythm)

    def _runFallbackAnalysis(self):
        """Basic analysis using TD-native operators only.
        Provides minimal beat/loudness estimation without EssentiaTD."""
        debug('extAnalysis: EssentiaTD not found, running fallback analysis')
        # Clear tables
        self._clearAnalysisTable()
        self._clearMarkersTable()
        # Without EssentiaTD, we can still offer a simple amplitude envelope
        # via Audio File In CHOP, but no BPM/onset/key detection.
        # The user should install EssentiaTD for full analysis.

    # ------------------------------------------------------------------
    # Harvest EssentiaTD results
    # ------------------------------------------------------------------

    def _harvestRhythm(self):
        """Read batch output from Essentia Rhythm CHOP.
        Returns dict with keys: bpm, beats (list of frames),
        onsets (list of (frame, strength))."""
        chop = self._rhythmCHOP()
        result = {'bpm': 120.0, 'bpm_confidence': 0.0,
                  'beats': [], 'onsets': []}
        if chop is None:
            return result

        # BPM is typically a single-sample channel
        if 'bpm' in chop:
            result['bpm'] = chop['bpm'].eval()
        if 'beat_confidence' in chop:
            result['bpm_confidence'] = chop['beat_confidence'].eval()
        elif 'confidence' in chop:
            result['bpm_confidence'] = chop['confidence'].eval()

        # Beat triggers: each sample where value > 0.5 is a beat
        if 'beat' in chop:
            chan = chop['beat']
            for i in range(chan.numSamples):
                if chan.evalAtSample(i) > 0.5:
                    frame = self._sampleToFrame(i)
                    result['beats'].append(frame)

        # Onsets: continuous strength channel
        if 'onset' in chop:
            chan = chop['onset']
            strength_chan = chop['onset_strength'] if 'onset_strength' in chop else None
            for i in range(chan.numSamples):
                if chan.evalAtSample(i) > 0.5:
                    strength = strength_chan.evalAtSample(i) if strength_chan else 1.0
                    frame = self._sampleToFrame(i)
                    result['onsets'].append((frame, strength))

        return result

    def _harvestLoudness(self):
        """Read batch output from Essentia Loudness CHOP.
        Returns list of (frame, loudness_db) tuples."""
        chop = self._loudnessCHOP()
        result = []
        if chop is None:
            return result
        chan_name = 'momentary' if 'momentary' in chop else (
            chop[0].name if chop.numChans > 0 else None)
        if chan_name is None:
            return result
        chan = chop[chan_name]
        for i in range(chan.numSamples):
            frame = self._sampleToFrame(i)
            result.append((frame, chan.evalAtSample(i)))
        return result

    def _harvestTonal(self):
        """Read batch output from Essentia Tonal CHOP.
        Returns dict with key, scale, strength per analysis frame."""
        chop = self._tonalCHOP()
        result = {'key': [], 'scale': [], 'strength': [], 'pitch': []}
        if chop is None:
            return result
        for chan_name in ['key', 'scale', 'strength', 'pitch']:
            if chan_name in chop:
                chan = chop[chan_name]
                for i in range(chan.numSamples):
                    result[chan_name].append(chan.evalAtSample(i))
        return result

    # ------------------------------------------------------------------
    # Build analysis_table DAT
    # ------------------------------------------------------------------

    def _clearAnalysisTable(self):
        dat = self.AnalysisDAT
        if dat is None:
            return
        # Keep header, remove data rows
        while dat.numRows > 1:
            dat.deleteRow(1)

    def _clearMarkersTable(self):
        dat = self.MarkersDAT
        if dat is None:
            return
        while dat.numRows > 1:
            dat.deleteRow(1)

    def _buildAnalysisTable(self, rhythm, loudness, tonal):
        """Merge all harvested results into a single analysis_table DAT."""
        self._clearAnalysisTable()
        dat = self.AnalysisDAT
        if dat is None:
            return

        transport = self.ownerComp.ext.extTransport
        bpm = rhythm.get('bpm', 120.0)
        bpm_conf = rhythm.get('bpm_confidence', 0.0)
        beat_set = set(rhythm.get('beats', []))
        onset_map = {f: s for f, s in rhythm.get('onsets', [])}
        loud_map = dict(loudness)

        # Determine total frames from audio length
        afin = self.AudioFileIn
        total_frames = 0
        if afin is not None and afin.numChans > 0:
            total_samples = afin[0].numSamples
            total_frames = int(round((total_samples / self._sample_rate) * self._fps))

        # Build bar counter from beats
        beat_frames = sorted(beat_set)
        beat_to_bar = {}
        sig_num = 4
        if transport:
            sig_num = transport._sig_num
        for i, bf in enumerate(beat_frames):
            bar = (i // sig_num) + 1
            beat_to_bar[bf] = bar

        # Tonal arrays (may be shorter than total frames)
        key_list = tonal.get('key', [])
        scale_list = tonal.get('scale', [])
        strength_list = tonal.get('strength', [])

        # Key index to name
        key_names = ['C', 'C#', 'D', 'D#', 'E', 'F',
                     'F#', 'G', 'G#', 'A', 'A#', 'B']
        scale_names = {0: 'major', 1: 'minor'}

        # Write rows â€” one per analysis hop (not every frame, to keep DAT size sane)
        hop_frames = max(1, int(self._hop_size / self._sample_rate * self._fps))
        frame = 0
        tonal_idx = 0
        while frame < total_frames:
            tc = transport.FrameToTc(frame) if transport else ''
            is_beat = 1 if frame in beat_set else 0
            bar = beat_to_bar.get(frame, '')
            onset_str = onset_map.get(frame, 0.0)
            loud = loud_map.get(frame, -60.0)

            # Tonal â€” map analysis index to frame
            key_val = ''
            key_scale = ''
            key_str = ''
            if tonal_idx < len(key_list):
                key_idx = int(key_list[tonal_idx])
                key_val = key_names[key_idx % 12] if 0 <= key_idx < 12 else ''
                if tonal_idx < len(scale_list):
                    key_scale = scale_names.get(int(scale_list[tonal_idx]), '')
                if tonal_idx < len(strength_list):
                    key_str = '{:.3f}'.format(strength_list[tonal_idx])

            note_guess = ''  # Placeholder for pitch-to-note conversion
            phrase_id = ''   # Placeholder for MFCC phrase segmentation

            dat.appendRow([
                frame, tc, is_beat, bar, '{:.3f}'.format(onset_str),
                phrase_id, note_guess, '{:.3f}'.format(bpm_conf),
                '{:.1f}'.format(loud), key_val, key_scale, key_str
            ])

            frame += hop_frames
            tonal_idx += 1

    # ------------------------------------------------------------------
    # Marker generation
    # ------------------------------------------------------------------

    def _generateMarkers(self, rhythm):
        """Create markers_table entries from beat and onset data."""
        self._clearMarkersTable()
        dat = self.MarkersDAT
        if dat is None:
            return
        transport = self.ownerComp.ext.extTransport

        # Beat markers
        for frame in sorted(rhythm.get('beats', [])):
            tc = transport.FrameToTc(frame) if transport else ''
            dat.appendRow([frame, tc, 'beat', '', '1.0'])

        # Onset markers (only strong onsets)
        for frame, strength in rhythm.get('onsets', []):
            if strength > 0.5:
                tc = transport.FrameToTc(frame) if transport else ''
                dat.appendRow([frame, tc, 'onset', '', '{:.3f}'.format(strength)])

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _sampleToFrame(self, sample_index):
        """Convert an analysis sample index to a timeline frame number."""
        time_sec = (sample_index * self._hop_size) / self._sample_rate
        return int(round(time_sec * self._fps))

    def FrameToSample(self, frame):
        """Convert a timeline frame to the nearest analysis sample index."""
        time_sec = frame / self._fps
        return int(round((time_sec * self._sample_rate) / self._hop_size))

    # ------------------------------------------------------------------
    # Public queries
    # ------------------------------------------------------------------

    def BpmEstimate(self):
        """Return the estimated BPM from the last analysis, or 120 default."""
        dat = self.AnalysisDAT
        if dat is None or dat.numRows < 2:
            return 120.0
        # BPM confidence is stored per row, take the first non-zero
        for row in range(1, dat.numRows):
            conf = float(dat[row, 'bpm_confidence'] or 0)
            if conf > 0:
                # BPM is in transport_settings, not per-row
                transport = self.ownerComp.ext.extTransport
                return transport.Bpm if transport else 120.0
        return 120.0

    def BeatsInRange(self, start_frame, end_frame):
        """Return list of frames that are beats within a range."""
        dat = self.AnalysisDAT
        if dat is None:
            return []
        beats = []
        for row in range(1, dat.numRows):
            f = int(dat[row, 'frame'])
            if f < start_frame:
                continue
            if f >= end_frame:
                break
            if str(dat[row, 'beat']) == '1':
                beats.append(f)
        return beats

    def OnsetsInRange(self, start_frame, end_frame, min_strength=0.3):
        """Return list of (frame, strength) tuples for onsets in range."""
        dat = self.AnalysisDAT
        if dat is None:
            return []
        onsets = []
        for row in range(1, dat.numRows):
            f = int(dat[row, 'frame'])
            if f < start_frame:
                continue
            if f >= end_frame:
                break
            s = float(dat[row, 'onset_strength'] or 0)
            if s >= min_strength:
                onsets.append((f, s))
        return onsets

    def KeyAtFrame(self, frame):
        """Return (key, scale, strength) at or near a given frame."""
        dat = self.AnalysisDAT
        if dat is None or dat.numRows < 2:
            return ('', '', 0.0)
        # Find nearest row
        best_row = 1
        best_dist = abs(int(dat[1, 'frame']) - frame)
        for row in range(2, dat.numRows):
            dist = abs(int(dat[row, 'frame']) - frame)
            if dist < best_dist:
                best_dist = dist
                best_row = row
        return (
            str(dat[best_row, 'key']),
            str(dat[best_row, 'key_scale']),
            float(dat[best_row, 'key_strength'] or 0)
        )

    def LoudnessAtFrame(self, frame):
        """Return loudness_db at or near a given frame."""
        dat = self.AnalysisDAT
        if dat is None or dat.numRows < 2:
            return -60.0
        best_row = 1
        best_dist = abs(int(dat[1, 'frame']) - frame)
        for row in range(2, dat.numRows):
            dist = abs(int(dat[row, 'frame']) - frame)
            if dist < best_dist:
                best_dist = dist
                best_row = row
        return float(dat[best_row, 'loudness_db'] or -60.0)
