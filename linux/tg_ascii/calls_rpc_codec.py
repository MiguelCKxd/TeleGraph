"""Explicit codecs for the pinned native media API; never deserialize arbitrary types."""
ENUMS = frozenset(('MediaSource', 'StreamMode', 'StreamDevice', 'VideoRotation',
    'ConnectionKind', 'ConnectionState', 'ConnectionMode', 'StreamStatus', 'StreamType',
    'CallType', 'MediaSegmentQuality', 'MediaSegmentPartStatus'))
SCHEMAS = {
    'MediaDescription': ('microphone', 'speaker', 'camera', 'screen'),
    'AudioDescription': ('media_source', 'sample_rate', 'channel_count', 'input', 'keep_open'),
    'VideoDescription': ('media_source', 'width', 'height', 'fps', 'input', 'keep_open'),
    'SsrcGroup': ('semantics', 'ssrcs'), 'SsrcMapping': ('user_id', 'ssrc'),
    'MediaState': ('muted', 'video_paused', 'video_stopped', 'presentation_paused', 'presentation_stopped'),
    'ConnectionInfo': ('state', 'kind'), 'CallInfo': ('playback', 'capture'),
    'SubchainRequest': ('subchain', 'height', 'limit'), 'ParticipantsRequest': ('ssrcs',),
    'Protocol': ('min_layer', 'max_layer', 'udp_p2p', 'udp_reflector', 'library_versions'),
    'ConferenceJoinParams': ('payload', 'public_key', 'block'),
    'Frame': ('ssrc', 'data', 'frame_data'),
    'FrameData': ('absolute_capture_timestamp_ms', 'rotation', 'width', 'height'),
    'SegmentPartRequest': ('segment_id', 'part_id', 'limit', 'timestamp', 'quality_update', 'channel_id', 'quality'),
}

METHODS = frozenset(('create_call', 'create_p2p_call', 'init_conference', 'connect', 'camera_effects',
    'set_source_volume', 'set_stream_sources', 'get_state', 'get_connection_mode', 'get_call_type', 'calls',
    'mute', 'unmute', 'pause', 'resume', 'stop', 'init_presentation', 'stop_presentation',
    'add_incoming_video', 'remove_incoming_video', 'update_audio_ssrc_mappings',
    'apply_blocks', 'finish_subchain_request', 'send_broadcast_timestamp', 'send_broadcast_part',
    'get_emojis_fingerprint', 'time', 'cpu_usage'))
EVENTS = frozenset(('on_connection_change', 'on_frames', 'on_stream_end', 'on_upgrade',
    'on_signaling_data',
    'on_update_emojis', 'on_outbound_block', 'on_subchain_request', 'on_request_participants',
    'on_request_broadcast_part', 'on_request_broadcast_timestamp'))


def encode(value, depth=0):
    if depth > 20:
        raise ValueError('Native IPC nesting limit exceeded')
    if value is None or type(value) in (bool, int, float, str, bytes):
        return value
    recurse = lambda item: encode(item, depth + 1)
    if isinstance(value, (list, tuple)):
        if len(value) > 10000:
            raise ValueError('Native IPC sequence limit exceeded')
        return ('sequence', tuple(recurse(item) for item in value))
    if isinstance(value, dict):
        if len(value) > 10000:
            raise ValueError('Native IPC map limit exceeded')
        return ('mapping', tuple((recurse(key), recurse(item)) for key, item in value.items()))
    name = type(value).__name__
    if type(value).__module__ != 'ntgcalls':
        raise ValueError('Unsupported native IPC type')
    if name in ENUMS:
        return ('enum', name, value.value)
    if name in SCHEMAS:
        return ('record', name, tuple(recurse(getattr(value, key)) for key in SCHEMAS[name]))
    raise ValueError('Unsupported native IPC record: ' + name)


def decode(value, depth=0):
    if depth > 20:
        raise ValueError('Native IPC nesting limit exceeded')
    if value is None or type(value) in (bool, int, float, str, bytes):
        return value
    if not isinstance(value, tuple) or not value:
        raise ValueError('Invalid native IPC value')
    recurse = lambda item: decode(item, depth + 1)
    if value[0] in ('sequence', 'mapping') and len(value) == 2:
        if len(value[1]) > 10000:
            raise ValueError('Native IPC collection limit exceeded')
        if value[0] == 'sequence':
            return [recurse(item) for item in value[1]]
        return {recurse(key): recurse(item) for key, item in value[1]}
    import ntgcalls as nt
    if value[0] == 'enum' and len(value) == 3 and value[1] in ENUMS:
        return getattr(nt, value[1])(value[2])
    if value[0] == 'record' and len(value) == 3 and value[1] in SCHEMAS:
        if len(value[2]) != len(SCHEMAS[value[1]]):
            raise ValueError('Invalid native IPC record fields')
        return getattr(nt, value[1])(*(recurse(item) for item in value[2]))
    raise ValueError('Unknown native IPC tag')
