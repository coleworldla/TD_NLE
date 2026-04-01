"""
extSequencer - Master per-frame orchestrator for TD_NLE.

This is the top-level cook-loop driver. Each frame it:
    1. Asks extTransport for the current frame
    2. Asks extPlayerPool to assign clips to players
    3. Evaluates active notes and cues from notes_table
    4. Samples automation from automation_table
    5. Updates Layer Mix TOP inputs
    6. Feeds the final output to preview and record
"""

import json


class extSequencer:

    def __init__(self, ownerComp):
        self.ownerComp = ownerComp
        self._last_frame = -1
        self._active_notes = []

    @property
    def Transport(self):
        return self.ownerComp.ext.extTransport

    @property
    def PlayerPool(self):
        return self.ownerComp.ext.extPlayerPool

    @property
    def NotesDAT(self):
        return self.ownerComp.op('model/notes_table')

    @property
    def AutomationDAT(self):
        return self.ownerComp.op('model/automation_table')

    @property
    def TracksDAT(self):
        return self.ownerComp.op('model/tracks_table')

    @property
    def LayerMix(self):
        return self.ownerComp.op('mix/layermix_main')

    @property
    def Recorder(self):
        return getattr(self.ownerComp.ext, 'extRecorder', None)

    def Tick(self):
        frame = self.Transport.CurrentFrame()
        if frame == self._last_frame and self.Transport.Playing:
            return frame

        track_filter = self._buildTrackFilter()
        active_assignments = self.PlayerPool.Update(frame, clip_filter=track_filter)

        self._evaluateNotes(frame)
        self._sampleAutomation(frame)
        self._updateLayerMix(active_assignments)

        recorder = self.Recorder
        if recorder is not None and recorder.IsRecording:
            recorder.UpdateBurnin(frame)

        self._last_frame = frame
        return frame

    def _buildTrackFilter(self):
        dat = self.TracksDAT
        if dat is None or dat.numRows < 2:
            return lambda clip: True

        track_mute = {}
        track_solo = {}
        any_solo = False
        for row in range(1, dat.numRows):
            track = str(dat[row, 'track'])
            track_mute[track] = str(dat[row, 'mute']) == '1'
            track_solo[track] = str(dat[row, 'solo']) == '1'
            any_solo = any_solo or track_solo[track]

        def clip_filter(clip):
            track = clip.get('track', '')
            if any_solo:
                return track_solo.get(track, False)
            return not track_mute.get(track, False)

        return clip_filter

    def _evaluateNotes(self, frame):
        dat = self.NotesDAT
        if dat is None or dat.numRows < 2:
            self._active_notes = []
            return

        newly_active = []
        for row in range(1, dat.numRows):
            start = int(dat[row, 'start_frame'])
            duration = int(dat[row, 'duration_frames'] or 1)
            end = start + duration
            if start <= frame < end:
                note = {}
                for col in range(dat.numCols):
                    note[str(dat[0, col])] = str(dat[row, col])
                newly_active.append(note)
                if frame == start:
                    self._fireNote(note)
        self._active_notes = newly_active

    def _fireNote(self, note):
        event_type = note.get('event_type', '')
        target = note.get('target', '')
        value = note.get('value', '')
        velocity = float(note.get('velocity', 1.0))

        if event_type == 'scene_launch':
            self._setClipEnabled(target, True)
        elif event_type == 'trigger':
            self._sendTrigger(target, velocity)
        elif event_type == 'blend_mode':
            self._setClipBlendMode(target, value)
        elif event_type == 'par_set':
            self._setParameter(target, value)
        elif event_type == 'morph_preset':
            self._morphPreset(target, value, note.get('params_json', ''))
        elif event_type == 'jump_preset':
            self._jumpPreset(target, value)
        elif event_type == 'random_morph':
            self._randomMorph(target, value)
        elif event_type == 'preset_sequence':
            self._presetSequence(target, value)
        elif event_type == 'osc':
            self._sendOsc(target, value)
        elif event_type == 'midi_note':
            self._sendMidiNote(target, value, velocity)

    def _setClipEnabled(self, clip_id, enabled):
        dat = self.ownerComp.op('model/clips_table')
        if dat is None:
            return
        for row in range(1, dat.numRows):
            if str(dat[row, 'id']) == str(clip_id):
                dat[row, 'enabled'] = '1' if enabled else '0'
                break

    def _sendTrigger(self, target, velocity):
        target_op = self.ownerComp.op(target)
        if target_op is not None and hasattr(target_op.par, 'Trigger'):
            target_op.par.Trigger.pulse()

    def _setClipBlendMode(self, clip_id, blend_mode):
        dat = self.ownerComp.op('model/clips_table')
        if dat is None:
            return
        for row in range(1, dat.numRows):
            if str(dat[row, 'id']) == str(clip_id):
                dat[row, 'blend_mode'] = blend_mode
                break

    def _setParameter(self, target, value):
        if ':' not in target:
            return
        op_path, par_name = target.rsplit(':', 1)
        target_op = self.ownerComp.op(op_path)
        if target_op is not None and hasattr(target_op.par, par_name):
            par = getattr(target_op.par, par_name)
            coerced = self._coerceValue(value)
            if hasattr(par, 'pulse') and str(coerced).lower() in ('pulse', 'trigger'):
                par.pulse()
            else:
                par.val = coerced

    def _coerceValue(self, value):
        text = str(value).strip()
        if text == '':
            return ''
        if text[0] in '[{"':
            try:
                return json.loads(text)
            except Exception:
                pass
        lowered = text.lower()
        if lowered == 'true':
            return True
        if lowered == 'false':
            return False
        try:
            return int(text)
        except ValueError:
            pass
        try:
            return float(text)
        except ValueError:
            return text

    def _presetManager(self, target_path=''):
        return self.ownerComp.op(target_path or 'scripts/preset_manager')

    def _morphPreset(self, target_path, preset_name, params_json):
        preset_manager = self._presetManager(target_path)
        if preset_manager is None or not hasattr(preset_manager, 'MorphPreset'):
            return
        params = {}
        if params_json:
            try:
                params = json.loads(params_json)
            except Exception:
                params = {}
        morph_time = params.get('morphTime', 1.0)
        morph_curve = params.get('morphCurve', 'linear')
        preset_manager.MorphPreset(preset_name, morphTime=morph_time, morphCurve=morph_curve)

    def _jumpPreset(self, target_path, preset_name):
        preset_manager = self._presetManager(target_path)
        if preset_manager is not None and hasattr(preset_manager, 'JumpToPreset'):
            preset_manager.JumpToPreset(preset_name)

    def _randomMorph(self, target_path, mode):
        preset_manager = self._presetManager(target_path)
        if preset_manager is not None and hasattr(preset_manager, 'RandomMorph'):
            preset_manager.RandomMorph(mode=mode or 'Uniform')

    def _presetSequence(self, target_path, value):
        preset_manager = self._presetManager(target_path)
        if preset_manager is None or not hasattr(preset_manager, 'PresetsSequence'):
            return
        keys = [key.strip() for key in str(value).split(',') if key.strip()]
        preset_manager.PresetsSequence(keysSequence=keys)

    def _sendOsc(self, address, value):
        osc_out = self.ownerComp.op('scripts/osc_out')
        if osc_out is not None:
            osc_out.sendOSC(address, [value])

    def _sendMidiNote(self, channel_note, value, velocity):
        pass

    def _sampleAutomation(self, frame):
        dat = self.AutomationDAT
        if dat is None or dat.numRows < 2:
            return
        for row in range(1, dat.numRows):
            start = int(dat[row, 'start_frame'])
            end = int(dat[row, 'end_frame'])
            if not (start <= frame <= end):
                continue
            target_path = str(dat[row, 'target_path'])
            target_par = str(dat[row, 'target_par'])
            lane_id = str(dat[row, 'id'])
            keyframe_chop = self.ownerComp.op('automation/lane_{}'.format(lane_id))
            if keyframe_chop is None or keyframe_chop.numChans <= 0:
                continue
            local_frame = frame - start
            value = keyframe_chop[0].evalAtSample(local_frame)
            target_op = self.ownerComp.op(target_path)
            if target_op is not None and hasattr(target_op.par, target_par):
                setattr(target_op.par, target_par, value)

    def _updateLayerMix(self, active_assignments):
        layer_mix = self.LayerMix
        if layer_mix is None:
            return
        for visual_index in range(self.PlayerPool.PoolSize):
            opacity = 0.0
            blend = 'over'
            for assignment_index, clip in active_assignments:
                if assignment_index == visual_index:
                    opacity = float(clip.get('opacity', 1.0))
                    blend = clip.get('blend_mode', 'over')
                    break
            opacity_par = 'Opacity{}'.format(visual_index)
            if hasattr(layer_mix.par, opacity_par):
                setattr(layer_mix.par, opacity_par, opacity)
            blend_par = 'Blend{}'.format(visual_index)
            if hasattr(layer_mix.par, blend_par):
                setattr(layer_mix.par, blend_par, blend)

    def ActiveNotes(self):
        return list(self._active_notes)

    def ClipAtFrame(self, frame, track=None):
        clips = self.PlayerPool.ActiveClipsAtFrame(frame)
        if track is not None:
            clips = [clip for clip in clips if clip.get('track') == str(track)]
        return clips
