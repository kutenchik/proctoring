"""Closed, bounded diagnostic schema. Never accept arbitrary exception text."""
import re
from datetime import datetime
from .screen_geometry import valid_geometry

SCREEN_CODES = frozenset(('unknown_failure', 'capture_unavailable', 'capture_bitmap_invalid', 'capture_mask_invalid', 'single_display_required', 'privacy_mask_unavailable', 'capture_geometry_changed', 'monitor_capture_unavailable', 'mask_query_failed', 'monitor_capture_failed', 'image_encode_failed', 'owner_destroyed', 'session_not_active', 'authorization_ended', 'authorization_expired', 'consent_lost', 'backend_disconnected', 'control_disconnected', 'host_channel_unavailable', 'invalid_host_message', 'invalid_stream_message', 'invalid_stream_ready', 'invalid_stream_renewal', 'stream_authorization_ended', 'stream_network_error', 'stream_disconnected', 'frame_delivery_unavailable', 'stopped', 'viewer_changed', 'viewer_switched', 'viewer_replaced', 'teacher_stopped', 'session_ended', 'application_shutdown', 'display_changed', 'student_offline', 'live_queue_full', 'disconnected', 'direct_timeout', 'direct_failed', 'direct_renderer_unavailable', 'direct_start_failed', 'direct_unavailable', 'rtc_channel_closed', 'rtc_connection_failed', 'rtc_operation_failed', 'socket_cleanup_failed', 'rtc_cleanup_failed', 'diagnostic_delivery_failed', 'stream_send_failed', 'invalid_credential', 'invalid_live_auth', 'invalid_live_message', 'invalid_message', 'message_limit', 'message_rate', 'origin_rejected', 'connection_replaced', 'frame_limit', 'invalid_frame', 'invalid_frame_ack', 'invalid_quality', 'invalid_signal', 'invalid_transport', 'invalid_viewer', 'login_required', 'not_found', 'signal_limit', 'viewer_expired', 'viewer_forbidden'))


def safe_code(value):
    return value if isinstance(value, str) and value in SCREEN_CODES else 'unknown_failure'


def valid_diagnostic(v):
    keys = {'timestamp','generation','viewer_id','component','phase','code','description','transport',
            'capture_state','viewer_state','requested','ws_close_code','ws_close_reason','transition','fallback','secondary'}
    if isinstance(v, dict) and 'delivery_trace' in v:
        if not valid_delivery_trace(v['delivery_trace']):
            return False
        keys.add('delivery_trace')
    if isinstance(v, dict) and 'geometry' in v:
        if not valid_geometry(v['geometry']):
            return False
        keys.add('geometry')
    if not isinstance(v, dict) or set(v) != keys:
        return False
    try:
        datetime.strptime(v['timestamp'], '%Y-%m-%dT%H:%M:%S.%fZ')
        return (type(v['generation']) is int and 0 <= v['generation'] < 2**53 and
            isinstance(v['viewer_id'], str) and re.fullmatch('[a-f0-9]{32}', v['viewer_id']) is not None and
            v['component'] in ('capture','sender','stream_socket','authorization') and v['phase'] in ('capture','stop') and
            v['code'] in SCREEN_CODES and v['description'] == v['code'].replace('_',' ') and
            v['transport'] in (None,'direct','relay') and v['capture_state'] in ('in_flight','idle') and
            v['viewer_state'] in ('pending','attached') and type(v['requested']) is bool and
            (v['ws_close_code'] is None or type(v['ws_close_code']) is int and 1000 <= v['ws_close_code'] <= 4999) and
            (v['ws_close_reason'] in (None,'','redacted') or v['ws_close_reason'] in SCREEN_CODES) and
            v['transition'] == 'lease_revoked' and (v['fallback'] is None or v['fallback'] in SCREEN_CODES) and
            isinstance(v['secondary'],list) and len(v['secondary']) <= 4 and all(c in SCREEN_CODES for c in v['secondary']))
    except (ValueError, TypeError):
        return False


def valid_delivery_trace(v):
    stages = {'capture_start','capture_ready','capture_discard','send','send_blocked','ack_received','ack_accepted','ack_rejected','ack_evicted','frame_received','frame_replaced','decode_start','decode_discard','decode_failed','presented','ack_sent','fallback'}
    def number(n):
        return type(n) is int and 0 <= n < 2**53
    return (isinstance(v, dict) and set(v) == {'counts','records'} and isinstance(v['counts'],dict)
            and all(k in stages and number(n) for k,n in v['counts'].items())
            and isinstance(v['records'],list) and len(v['records']) <= 128
            and all(isinstance(r,dict) and set(r) == {'stage','sequence','at_ms','value'} and isinstance(r['stage'],str) and r['stage'] in stages
                    and type(r['sequence']) is int and -1 <= r['sequence'] < 2**53
                    and number(r['at_ms']) and number(r['value']) and r['value'] <= 10**9 for r in v['records']))
