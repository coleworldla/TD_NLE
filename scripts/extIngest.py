"""
extIngest - Drag-and-drop ingest for TD_NLE.

Adds .tox, video, and audio clips to clips_table while preserving
nondestructive trim metadata. The timeline stays frame-based, while clips
store source trim points plus optional source fps metadata so playback can
resolve source time nondestructively at run time.
"""

import os


class extIngest:

    TOX_EXTENSIONS = {'.tox', '.toe'}
    VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.wmv', '.mpeg', '.mpg', '.webm', '.mkv', '.gif'}
    AUDIO_EXTENSIONS = {'.wav', '.aif', '.aiff', '.mp3', '.flac', '.ogg', '.m4a'}
    ALL_SUPPORTED = TOX_EXTENSIONS | VIDEO_EXTENSIONS | AUDIO_EXTENSIONS

    def __init__(self, ownerComp):
        self.ownerComp = ownerComp

    @property
    def ClipsDAT(self):
        return self.ownerComp.op('model/clips_table')

    @property
    def TracksDAT(self):
        return self.ownerComp.op('model/tracks_table')

    @property
    def Transport(self):
        return getattr(self.ownerComp.ext, 'extTransport', None)

    def IngestFile(self, path, track=None, start_frame=None, shell_type=None):
        normalized_path = os.path.normpath(path)
        media_type = self._detectType(normalized_path)
        if media_type is None:
            debug('extIngest: unsupported file {}'.format(normalized_path))
            return None

        project_fps = self._projectFps()
        if track is None:
            track = self._nextAvailableTrack()
        if start_frame is None:
            start_frame = self._placeAtEnd(track)

        detected = self._detectShellType(media_type, normalized_path)
        shell_type = shell_type if shell_type else detected

        if media_type == 'video':
            duration_frames, fps = self._probeVideo(normalized_path, project_fps)
        elif media_type == 'audio':
            duration_frames = self._probeAudio(normalized_path, project_fps)
            fps = 0.0
        else:
            duration_frames, fps = self._probeTox(normalized_path)

        return self._createClipRow(
            media_type=media_type,
            shell_type=shell_type,
            file_path=normalized_path,
            track=track,
            start_frame=start_frame,
            duration_frames=duration_frames,
            fps=fps,
            source_in=0,
            source_out=-1,
        )

    def BrowseAndIngest(self, track=None, start_frame=None, shell_type='scene3d'):
        """Open a file picker and ingest the chosen file with the given shell_type."""
        path = ui.chooseFile(
            load=True,
            start=self._templateRoot() or '.',
            fileTypes=['.tox', '.toe', '.mp4', '.mov', '.avi', '.webm', '.gif',
                       '.wav', '.aif', '.aiff', '.mp3', '.flac', '.m4a'],
            title='Select Template or Media File',
        )
        if not path:
            return None
        return self.IngestFile(path=path, track=track, start_frame=start_frame,
                               shell_type=shell_type)

    def SetClipShellType(self, clip_id, shell_type):
        """Change the shell_type of an existing clip row (called from inspector)."""
        dat = self.ClipsDAT
        if dat is None:
            return False
        for row in range(1, dat.numRows):
            if str(dat[row, 'id']) == str(clip_id):
                dat[row, 'shell_type'] = shell_type
                return True
        return False

    def _templateRoot(self):
        settings = self.ownerComp.op('model/project_settings')
        if settings is None:
            return ''
        cell = settings['template_root', 'value']
        return str(cell.val) if cell is not None else ''

    def _detectShellType(self, media_type, path):
        if media_type == 'video':
            return 'video'
        if media_type == 'audio':
            return 'audio'
        # tox: infer from folder name conventions
        lower = path.lower().replace('\\', '/')
        if '/fx/' in lower or '/fx_' in lower or 'effect' in lower:
            return 'fx'
        if '/2d/' in lower or 'scene2d' in lower or '/comp/' in lower:
            return 'scene2d'
        return 'scene3d'

    def _detectType(self, path):
        extension = os.path.splitext(path)[1].lower()
        if extension in self.TOX_EXTENSIONS:
            return 'tox'
        if extension in self.VIDEO_EXTENSIONS:
            return 'video'
        if extension in self.AUDIO_EXTENSIONS:
            return 'audio'
        return None

    def _probeVideo(self, path, project_fps):
        probe_name = '_ingest_probe_video'
        self._destroyProbe(probe_name)
        try:
            probe = self.ownerComp.create(moviefileinTOP, probe_name)
            if hasattr(probe.par, 'file'):
                probe.par.file = path
            if hasattr(probe.par, 'reloadpulse'):
                probe.par.reloadpulse.pulse()
            probe.cook(force=True)
            source_length = self._operatorInfoValue(probe, ('length', 'file_length'), fallback=getattr(probe, 'numImages', 0))
            fps = self._operatorInfoValue(probe, ('sample_rate', 'rate'), fallback=project_fps)
            duration_seconds = 0.0
            if source_length and fps:
                duration_seconds = float(source_length) / float(fps)
            duration_frames = int(round(duration_seconds * project_fps)) if duration_seconds > 0 else 150
            return max(1, duration_frames), float(fps or project_fps)
        except Exception:
            debug('extIngest: video probe failed for {}'.format(path))
            return 150, float(project_fps)
        finally:
            self._destroyProbe(probe_name)

    def _probeAudio(self, path, project_fps):
        probe_name = '_ingest_probe_audio'
        self._destroyProbe(probe_name)
        try:
            probe = self.ownerComp.create(audiofileinCHOP, probe_name)
            if hasattr(probe.par, 'file'):
                probe.par.file = path
            if hasattr(probe.par, 'reloadpulse'):
                probe.par.reloadpulse.pulse()
            if hasattr(probe.par, 'timeslice'):
                probe.par.timeslice = False
            probe.cook(force=True)
            duration_seconds = self._operatorInfoValue(probe, ('file_length', 'true_file_length'), fallback=0.0)
            if duration_seconds <= 0:
                duration_frames = self._operatorInfoValue(
                    probe,
                    ('file_length_frames', 'true_file_length_frames'),
                    fallback=0.0,
                )
                if duration_frames > 0:
                    return max(1, int(round(duration_frames)))
            if duration_seconds <= 0 and hasattr(probe, 'numSamples') and hasattr(probe, 'sampleRate'):
                if probe.sampleRate:
                    duration_seconds = float(probe.numSamples) / float(probe.sampleRate)
            if duration_seconds > 0:
                return max(1, int(round(duration_seconds * project_fps)))
            return 150
        except Exception:
            debug('extIngest: audio probe failed for {}'.format(path))
            return 150
        finally:
            self._destroyProbe(probe_name)

    def _probeTox(self, path):
        return (150, 0.0)

    def _operatorInfoValue(self, operator, channel_names, fallback=0.0):
        info_chop = getattr(operator, 'infoCHOP', None)
        if info_chop is not None:
            for name in channel_names:
                try:
                    if name in info_chop:
                        return float(info_chop[name].eval())
                except Exception:
                    pass
        info_method = getattr(operator, 'info', None)
        if callable(info_method):
            try:
                info = info_method()
                for name in channel_names:
                    if name in info:
                        return float(info[name])
            except Exception:
                pass
        for name in channel_names:
            try:
                if hasattr(operator, name):
                    return float(getattr(operator, name))
            except Exception:
                pass
        return fallback

    def _destroyProbe(self, name):
        probe = self.ownerComp.op(name)
        if probe is not None:
            probe.destroy()

    def _createClipRow(self, media_type, shell_type, file_path, track,
                       start_frame, duration_frames, fps, source_in=0,
                       source_out=-1):
        dat = self.ClipsDAT
        if dat is None:
            return None
        clip_id = self._nextClipId()
        start_frame = int(start_frame)
        duration_frames = max(1, int(duration_frames))
        end_frame = start_frame + duration_frames
        transport = self.Transport
        start_tc = transport.FrameToTc(start_frame) if transport is not None else ''
        end_tc = transport.FrameToTc(end_frame) if transport is not None else ''
        # 23-column order: id, track, template_path, shell_type, subcomp,
        # start_frame, duration_frames, start_tc, end_tc, in_offset, out_offset,
        # opacity, blend_mode, transition_in, transition_out, preroll_frames,
        # enabled, overrides_json, media_type, source_in, source_out, fps, preset_name
        dat.appendRow([
            clip_id,
            int(track),
            file_path,
            shell_type,
            '',
            start_frame,
            duration_frames,
            start_tc,
            end_tc,
            0,
            0,
            1.0,
            'over',
            '',
            '',
            0,
            1,
            '',
            media_type,
            int(source_in),
            int(source_out),
            float(fps or 0.0),
            '',
        ])
        return clip_id

    def _nextClipId(self):
        dat = self.ClipsDAT
        if dat is None or dat.numRows < 2:
            return 1
        max_id = 0
        for row in range(1, dat.numRows):
            try:
                max_id = max(max_id, int(dat[row, 'id']))
            except Exception:
                pass
        return max_id + 1

    def _nextAvailableTrack(self):
        dat = self.TracksDAT
        if dat is None or dat.numRows < 2:
            return 0
        try:
            return int(dat[1, 'track'])
        except Exception:
            return 0

    def _placeAtEnd(self, track):
        dat = self.ClipsDAT
        if dat is None or dat.numRows < 2:
            return 0
        max_end = 0
        for row in range(1, dat.numRows):
            try:
                if str(dat[row, 'track']) != str(track):
                    continue
                start = int(dat[row, 'start_frame'])
                duration = int(dat[row, 'duration_frames'])
                max_end = max(max_end, start + duration)
            except Exception:
                pass
        return max_end

    def _projectFps(self):
        transport = self.Transport
        if transport is not None:
            return float(transport.Fps)
        return 30.0