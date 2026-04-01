"""
extPlayerPool - Manages reusable scene and media playback slots for TD_NLE.

Scene clips use the scene pool and remain Engine-COMP-driven. Dragged video
and audio clips use the media pool and resolve source trim/fps metadata into
seconds so playback remains nondestructive.
"""

import json


class extPlayerPool:

    SCENE_PLAYER_NAMES = ('player_1', 'player_2', 'player_3', 'player_4')
    MEDIA_PLAYER_NAMES = (
        'player_1', 'player_2', 'player_3', 'player_4',
        'media_player_1', 'media_player_2', 'media_player_3', 'media_player_4',
    )

    def __init__(self, ownerComp):
        self.ownerComp = ownerComp
        self._slots = []
        self._assignments = {}
        self._preloaded = {}
        self._initPool()

    @property
    def PoolSize(self):
        return len(self._slots)

    @property
    def ClipsDAT(self):
        return self.ownerComp.op('model/clips_table')

    def _initPool(self):
        self._slots = []
        players_root = self.ownerComp.op('players')
        if players_root is None:
            self._assignments = {}
            return

        scene_root = players_root.op('scene_players')
        media_root = players_root.op('media_players')

        if scene_root is not None:
            self._registerSlots(scene_root, self.SCENE_PLAYER_NAMES, 'scene')
        else:
            self._registerSlots(players_root, self.SCENE_PLAYER_NAMES, 'scene')

        if media_root is not None:
            self._registerSlots(media_root, self.MEDIA_PLAYER_NAMES, 'media')
        else:
            self._registerSlots(
                players_root,
                ('media_player_1', 'media_player_2', 'media_player_3', 'media_player_4'),
                'media',
            )

        for visual_index, slot in enumerate(self._slots):
            slot['visual_index'] = visual_index

        self._assignments = {index: None for index in range(len(self._slots))}

    def _registerSlots(self, root_comp, names, pool_kind):
        existing_paths = {slot['comp'].path for slot in self._slots}
        for name in names:
            player = root_comp.op(name)
            if player is None or player.path in existing_paths:
                continue
            self._slots.append({
                'comp': player,
                'pool_kind': pool_kind,
                'visual_index': None,
            })
            existing_paths.add(player.path)

    def ActiveClipsAtFrame(self, frame):
        dat = self.ClipsDAT
        if dat is None or dat.numRows < 2:
            return []
        clips = []
        for row in range(1, dat.numRows):
            if str(dat[row, 'enabled']) == '0':
                continue
            start = int(dat[row, 'start_frame'])
            duration = int(dat[row, 'duration_frames'])
            end = start + duration
            if start <= frame < end:
                clip = {}
                for col in range(dat.numCols):
                    clip[str(dat[0, col])] = str(dat[row, col])
                clips.append(clip)
        return clips

    def PrerollClipsAtFrame(self, frame):
        dat = self.ClipsDAT
        if dat is None or dat.numRows < 2:
            return []
        clips = []
        for row in range(1, dat.numRows):
            if str(dat[row, 'enabled']) == '0':
                continue
            start = int(dat[row, 'start_frame'])
            preroll = int(dat[row, 'preroll_frames'] or 0)
            if preroll > 0 and (start - preroll) <= frame < start:
                clip = {}
                for col in range(dat.numCols):
                    clip[str(dat[0, col])] = str(dat[row, col])
                clips.append(clip)
        return clips

    def Update(self, frame, clip_filter=None):
        active_clips = self._filterClips(self.ActiveClipsAtFrame(frame), clip_filter)
        preroll_clips = self._filterClips(self.PrerollClipsAtFrame(frame), clip_filter)
        active_ids = {clip['id'] for clip in active_clips}
        preroll_ids = {clip['id'] for clip in preroll_clips}

        for slot_index, clip_id in list(self._assignments.items()):
            if clip_id is not None and clip_id not in active_ids and clip_id not in preroll_ids:
                self._unloadPlayer(slot_index)
                self._assignments[slot_index] = None
                self._preloaded.pop(clip_id, None)

        for clip in active_clips:
            clip_id = clip['id']
            slot_index = self._slotIndexForClip(clip_id)
            if slot_index is None:
                slot_index = self._findFreeSlot(clip)
                if slot_index is None:
                    debug('extPlayerPool: no free {} slot for clip {}'.format(
                        self._eligiblePoolKind(clip), clip_id
                    ))
                    continue
                self._assignments[slot_index] = clip_id
                self._loadPlayer(slot_index, clip)
            self._preloaded.pop(clip_id, None)
            self._drivePlayer(slot_index, clip, frame, active=True)

        for clip in preroll_clips:
            clip_id = clip['id']
            if self._slotIndexForClip(clip_id) is not None or clip_id in self._preloaded:
                continue
            slot_index = self._findFreeSlot(clip)
            if slot_index is None:
                continue
            self._assignments[slot_index] = clip_id
            self._preloaded[clip_id] = slot_index
            self._loadPlayer(slot_index, clip)
            self._drivePlayer(slot_index, clip, frame, active=False, preroll=True)

        visual_assignments = []
        for slot_index, clip_id in self._assignments.items():
            if clip_id is None or clip_id not in active_ids:
                continue
            clip = next((item for item in active_clips if item['id'] == clip_id), None)
            if clip is None or not self._clipProducesVisual(clip):
                continue
            visual_index = self._slots[slot_index]['visual_index']
            visual_assignments.append((visual_index, clip))
        return visual_assignments

    def _filterClips(self, clips, clip_filter):
        if clip_filter is None:
            return list(clips)
        return [clip for clip in clips if clip_filter(clip)]

    def _clipMediaType(self, clip):
        media_type = clip.get('media_type', 'tox') or 'tox'
        return media_type.lower()

    def _clipProducesVisual(self, clip):
        return self._clipMediaType(clip) != 'audio'

    def _eligiblePoolKind(self, clip):
        return 'scene' if self._clipMediaType(clip) == 'tox' else 'media'

    def _findFreeSlot(self, clip):
        desired_kind = self._eligiblePoolKind(clip)
        for slot_index, slot in enumerate(self._slots):
            if slot['pool_kind'] != desired_kind:
                continue
            if self._assignments.get(slot_index) is None:
                return slot_index
        return None

    def _slotIndexForClip(self, clip_id):
        for slot_index, assigned_clip_id in self._assignments.items():
            if assigned_clip_id == clip_id:
                return slot_index
        return None

    def _sceneTarget(self, player):
        engine = player.op('engine_comp')
        return engine if engine is not None else player

    def _sceneLoadMode(self, player):
        target = self._sceneTarget(player)
        if hasattr(target.par, 'file'):
            return ('engine', target)
        if hasattr(target.par, 'externaltox'):
            return ('externaltox', target)
        return ('unknown', target)

    def _loadPlayer(self, slot_index, clip):
        slot = self._slots[slot_index]
        if slot['pool_kind'] == 'scene':
            self._loadScenePlayer(slot['comp'], clip)
        else:
            self._loadMediaPlayer(slot['comp'], clip)

    def _unloadPlayer(self, slot_index):
        slot = self._slots[slot_index]
        if slot['pool_kind'] == 'scene':
            self._unloadScenePlayer(slot['comp'])
        else:
            self._unloadMediaPlayer(slot['comp'])

    def _drivePlayer(self, slot_index, clip, global_frame, active=True, preroll=False):
        slot = self._slots[slot_index]
        if slot['pool_kind'] == 'scene':
            self._driveScenePlayer(slot['comp'], clip, global_frame, active, preroll)
        else:
            self._driveMediaPlayer(slot['comp'], clip, global_frame, active, preroll)

    def _loadScenePlayer(self, player, clip):
        file_path = clip.get('template_path', '')
        if not file_path:
            return
        load_mode, target = self._sceneLoadMode(player)
        subcomp = clip.get('subcomp', '')
        if load_mode == 'engine':
            if hasattr(target.par, 'clock'):
                target.par.clock = 'synced'
            if hasattr(target.par, 'reloadoncrash'):
                target.par.reloadoncrash = True
            target.par.file = file_path
            if hasattr(target.par, 'reloadpulse'):
                target.par.reloadpulse.pulse()
            elif hasattr(target.par, 'reload'):
                target.par.reload.pulse()
        elif load_mode == 'externaltox':
            if hasattr(target.par, 'enableexternaltox'):
                target.par.enableexternaltox = True
            if hasattr(target.par, 'subcompname'):
                target.par.subcompname = subcomp
            target.par.externaltox = file_path
            if hasattr(target.par, 'enableexternaltoxpulse'):
                target.par.enableexternaltoxpulse.pulse()
            elif hasattr(target.par, 'reinitnet'):
                target.par.reinitnet.pulse()
        player.store('subcomp', subcomp or '')
        self._selectVisualOutput(player, 0)

    def _unloadScenePlayer(self, player):
        load_mode, target = self._sceneLoadMode(player)
        par_target = target if hasattr(target.par, 'Active') else player
        if hasattr(par_target.par, 'Active'):
            par_target.par.Active = False
        if hasattr(par_target.par, 'Prewarm'):
            par_target.par.Prewarm = False
        if hasattr(par_target.par, 'Bypassrender'):
            par_target.par.Bypassrender = True
        if load_mode == 'engine':
            if hasattr(target.par, 'unload'):
                target.par.unload.pulse()
            elif hasattr(target.par, 'file'):
                target.par.file = ''
        elif load_mode == 'externaltox':
            if hasattr(target.par, 'subcompname'):
                target.par.subcompname = ''
            if hasattr(target.par, 'externaltox'):
                target.par.externaltox = ''
            if hasattr(target.par, 'reinitnet'):
                target.par.reinitnet.pulse()
        player.store('subcomp', '')

    def _driveScenePlayer(self, player, clip, global_frame, active=True, preroll=False):
        load_mode, target = self._sceneLoadMode(player)
        par_target = target if hasattr(target.par, 'Active') else player
        start = int(clip.get('start_frame', 0))
        duration = int(clip.get('duration_frames', 1))
        in_offset = int(clip.get('in_offset', 0))
        opacity = float(clip.get('opacity', 1.0))
        local_frame = max(0, (global_frame - start) + in_offset)
        progress = local_frame / max(1, duration)
        should_cook = active or preroll

        if hasattr(par_target.par, 'Active'):
            par_target.par.Active = should_cook
        if hasattr(par_target.par, 'Prewarm'):
            par_target.par.Prewarm = preroll
        if hasattr(par_target.par, 'Bypassrender'):
            par_target.par.Bypassrender = not should_cook
        if hasattr(par_target.par, 'Localtime'):
            par_target.par.Localtime = self._transportSeconds(local_frame)
        if hasattr(par_target.par, 'Clipprogress'):
            par_target.par.Clipprogress = max(0.0, min(1.0, progress))
        if hasattr(par_target.par, 'Opacity'):
            par_target.par.Opacity = opacity if active else 0.0

        params_json = clip.get('overrides_json', '')
        if params_json:
            try:
                params = json.loads(params_json)
                for key, value in params.items():
                    if hasattr(par_target.par, key):
                        setattr(par_target.par, key, value)
            except Exception:
                pass

    def _loadMediaPlayer(self, player, clip):
        file_path = clip.get('template_path', '')
        media_type = self._clipMediaType(clip)
        source_fps = self._clipSourceFps(clip)
        source_in_seconds = self._framesToSeconds(int(clip.get('source_in', 0) or 0), source_fps)
        source_out = int(clip.get('source_out', -1) or -1)
        source_out_seconds = self._framesToSeconds(source_out, source_fps) if source_out >= 0 else None

        movie_in = self._movieFileIn(player)
        audio_in = self._audioFileIn(player)
        engine = player.op('engine_comp')

        if engine is not None:
            if hasattr(engine.par, 'Active'):
                engine.par.Active = False
            if hasattr(engine.par, 'Bypassrender'):
                engine.par.Bypassrender = True

        if media_type == 'video' and movie_in is not None:
            if hasattr(movie_in.par, 'file'):
                movie_in.par.file = file_path
            if hasattr(movie_in.par, 'reloadpulse'):
                movie_in.par.reloadpulse.pulse()
            elif hasattr(movie_in.par, 'reload'):
                movie_in.par.reload.pulse()
            if hasattr(movie_in.par, 'playmode'):
                movie_in.par.playmode = 'specify'
            if hasattr(movie_in.par, 'indexunit'):
                movie_in.par.indexunit = 'seconds'
            self._applyTrimToMovie(movie_in, source_in_seconds, source_out_seconds)
            self._setActive(movie_in, True)
            self._setBypass(movie_in, False)
            self._clearMediaFile(audio_in)
            self._setActive(audio_in, False)
            self._setBypass(audio_in, True)
            self._selectVisualOutput(player, 1)
        elif media_type == 'audio' and audio_in is not None:
            if hasattr(audio_in.par, 'file'):
                audio_in.par.file = file_path
            if hasattr(audio_in.par, 'reloadpulse'):
                audio_in.par.reloadpulse.pulse()
            elif hasattr(audio_in.par, 'reload'):
                audio_in.par.reload.pulse()
            if hasattr(audio_in.par, 'playmode'):
                audio_in.par.playmode = 'specify'
            if hasattr(audio_in.par, 'indexunit'):
                audio_in.par.indexunit = 'seconds'
            self._applyTrimToAudio(audio_in, source_in_seconds, source_out_seconds)
            self._setActive(audio_in, True)
            self._setBypass(audio_in, False)
            self._clearMediaFile(movie_in)
            self._setActive(movie_in, False)
            self._setBypass(movie_in, True)
            self._selectVisualOutput(player, 0)

        self._applyPresetOnLoad(player, clip)

    def _unloadMediaPlayer(self, player):
        movie_in = self._movieFileIn(player)
        audio_in = self._audioFileIn(player)
        self._clearMediaFile(movie_in)
        self._clearMediaFile(audio_in)
        self._setActive(movie_in, False)
        self._setActive(audio_in, False)
        self._setBypass(movie_in, True)
        self._setBypass(audio_in, True)
        self._selectVisualOutput(player, 0)

    def _driveMediaPlayer(self, player, clip, global_frame, active=True, preroll=False):
        media_type = self._clipMediaType(clip)
        start = int(clip.get('start_frame', 0))
        duration = int(clip.get('duration_frames', 1))
        in_offset = int(clip.get('in_offset', 0))
        source_in = int(clip.get('source_in', 0) or 0)
        source_out = int(clip.get('source_out', -1) or -1)
        local_frame = max(0, min(duration - 1, (global_frame - start) + in_offset))
        source_fps = self._clipSourceFps(clip)
        project_fps = self._projectFps()
        source_start_seconds = self._framesToSeconds(source_in, source_fps)
        source_seconds = source_start_seconds + self._framesToSeconds(local_frame, project_fps)
        if source_out >= 0:
            source_end_seconds = self._framesToSeconds(source_out, source_fps)
            source_seconds = min(source_seconds, max(source_start_seconds, source_end_seconds))

        if media_type == 'video':
            movie_in = self._movieFileIn(player)
            if movie_in is None:
                return
            if hasattr(movie_in.par, 'indexunit'):
                movie_in.par.indexunit = 'seconds'
            if hasattr(movie_in.par, 'index'):
                movie_in.par.index = source_seconds
            self._setActive(movie_in, active or preroll)
            self._setBypass(movie_in, not (active or preroll))
        elif media_type == 'audio':
            audio_in = self._audioFileIn(player)
            if audio_in is None:
                return
            if hasattr(audio_in.par, 'indexunit'):
                audio_in.par.indexunit = 'seconds'
            if hasattr(audio_in.par, 'index'):
                audio_in.par.index = source_seconds
            self._setActive(audio_in, active)
            self._setBypass(audio_in, not active)

    def _applyPresetOnLoad(self, player, clip):
        preset_name = clip.get('preset_name', '')
        if not preset_name:
            return
        preset_manager = player.op('preset_manager') or self.ownerComp.op('scripts/preset_manager')
        if preset_manager is not None and hasattr(preset_manager, 'JumpToPreset'):
            try:
                preset_manager.JumpToPreset(preset_name)
            except Exception:
                pass

    def _movieFileIn(self, player):
        return player.op('movie_filein') or player.op('moviefilein1')

    def _audioFileIn(self, player):
        return player.op('audio_filein') or player.op('audiofilein1')

    def _audioOutput(self, player):
        return player.op('OUT_AUDIO') or player.op('audio_out')

    def _setBypass(self, operator, state):
        if operator is not None and hasattr(operator.par, 'bypass'):
            operator.par.bypass = bool(state)

    def _setActive(self, operator, state):
        if operator is not None and hasattr(operator.par, 'active'):
            operator.par.active = bool(state)

    def _clearMediaFile(self, operator):
        if operator is None:
            return
        if hasattr(operator.par, 'file'):
            operator.par.file = ''

    def _selectVisualOutput(self, player, index_value):
        switch = player.op('out_select_top')
        if switch is None:
            return
        if hasattr(switch.par, 'index'):
            switch.par.index = index_value
        elif hasattr(switch.par, 'Input'):
            switch.par.Input = index_value

    def _applyTrimToMovie(self, movie_in, start_seconds, end_seconds):
        enable_trim = end_seconds is not None
        if hasattr(movie_in.par, 'trim'):
            movie_in.par.trim = enable_trim
        if hasattr(movie_in.par, 'tstartunit'):
            movie_in.par.tstartunit = 'seconds'
        if hasattr(movie_in.par, 'tstart'):
            movie_in.par.tstart = start_seconds
        if end_seconds is not None:
            if hasattr(movie_in.par, 'tendunit'):
                movie_in.par.tendunit = 'seconds'
            if hasattr(movie_in.par, 'tend'):
                movie_in.par.tend = end_seconds
        elif hasattr(movie_in.par, 'tend'):
            movie_in.par.tend = 0

    def _applyTrimToAudio(self, audio_in, start_seconds, end_seconds):
        enable_trim = end_seconds is not None
        if hasattr(audio_in.par, 'trim'):
            audio_in.par.trim = enable_trim
        if hasattr(audio_in.par, 'trimstartunit'):
            audio_in.par.trimstartunit = 'seconds'
        if hasattr(audio_in.par, 'trimstart'):
            audio_in.par.trimstart = start_seconds
        if end_seconds is not None:
            if hasattr(audio_in.par, 'trimendunit'):
                audio_in.par.trimendunit = 'seconds'
            if hasattr(audio_in.par, 'trimend'):
                audio_in.par.trimend = end_seconds
        elif hasattr(audio_in.par, 'trimend'):
            audio_in.par.trimend = 0

    def _clipSourceFps(self, clip):
        try:
            fps = float(clip.get('fps', clip.get('source_fps', 0)) or 0.0)
        except Exception:
            fps = 0.0
        return fps if fps > 0 else self._projectFps()

    def _framesToSeconds(self, frame_count, fps):
        fps = fps if fps > 0 else 30.0
        return float(frame_count) / fps

    def _projectFps(self):
        transport = getattr(self.ownerComp.ext, 'extTransport', None)
        if transport is not None:
            return float(transport.Fps)
        return 30.0

    def _timelineFramesToSeconds(self, frame_count, fps):
        return self._framesToSeconds(frame_count, fps)

    def _transportSeconds(self, frame_count):
        transport = getattr(self.ownerComp.ext, 'extTransport', None)
        if transport is not None:
            return transport.FrameToSeconds(frame_count)
        return self._timelineFramesToSeconds(frame_count, self._projectFps())

    def PlayerTOP(self, visual_index):
        slot = next((item for item in self._slots if item['visual_index'] == visual_index), None)
        if slot is None:
            return None
        player = slot['comp']
        output = player.op('OUT_TOP')
        if output is not None:
            return output
        subcomp = player.fetch('subcomp', '')
        if subcomp:
            subcomponent = player.op(subcomp)
            if subcomponent is not None:
                return subcomponent.op('OUT_TOP')
        scene_target = self._sceneTarget(player)
        if scene_target is not player:
            return scene_target.op('OUT_TOP')
        return None

    def ActivePlayerTOPs(self):
        tops = []
        for visual_index in range(self.PoolSize):
            top = self.PlayerTOP(visual_index)
            if top is not None:
                tops.append(top)
        return tops

    def ActiveAudioCHOPs(self):
        chops = []
        for slot_index, clip_id in self._assignments.items():
            if clip_id is None:
                continue
            player = self._slots[slot_index]['comp']
            audio_out = self._audioOutput(player)
            if audio_out is not None:
                chops.append(audio_out)
        return chops

    def DebugStatus(self):
        lines = ['extPlayerPool - {} slots'.format(self.PoolSize)]
        for slot_index, clip_id in self._assignments.items():
            slot = self._slots[slot_index]
            state = 'idle' if clip_id is None else 'clip {}'.format(clip_id)
            if clip_id in self._preloaded:
                state += ' (preroll)'
            lines.append('  {}:{} -> {}'.format(slot['pool_kind'], slot['comp'].name, state))
        return '\n'.join(lines)
