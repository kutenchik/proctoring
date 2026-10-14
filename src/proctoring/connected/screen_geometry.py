"""Fixed shape, numeric-only capture geometry evidence. No arbitrary strings."""
import math

STAGES = ('before_capture','before_mask','after_initial_mask','after_sources','after_final_mask','source_selection')
CHECKS = ('window_destroyed','web_contents_destroyed','display_count','display_id','content_x','content_y','content_width','content_height','display_bounds','display_size','display_scale','zoom','invalid_geometry','source_missing','source_ambiguous','source_empty','source_size')
EVENTS = ('focus','blur','resize','move','maximize','unmaximize','restore','minimize','enter-full-screen','leave-full-screen','closed','webcontents-destroyed','zoom-changed')

def shape(v, keys):
    return isinstance(v, dict) and set(v) == set(keys.split())

def numeric(v):
    return type(v) in (int, float) and abs(v) <= 2**53-1 and math.isfinite(v)

def nullable_number(v):
    return v is None or numeric(v)

def numbers(v, count):
    return v is None or isinstance(v, list) and len(v) == count and all(numeric(n) for n in v)

def nullable_bool(v):
    return v is None or type(v) is bool

def snapshot(v):
    return (shape(v, 'sampled_at window_destroyed web_contents_destroyed display_count display_id content display_bounds display_size display_scale zoom focused maximized') and numeric(v['sampled_at']) and v['sampled_at'] >= 0 and
        type(v['window_destroyed']) is bool and type(v['web_contents_destroyed']) is bool and
        type(v['display_count']) is int and 0 <= v['display_count'] <= 1024 and nullable_number(v['display_id']) and
        numbers(v['content'],4) and numbers(v['display_bounds'],4) and numbers(v['display_size'],2) and
        nullable_number(v['display_scale']) and nullable_number(v['zoom']) and nullable_bool(v['focused']) and nullable_bool(v['maximized']))

def valid_geometry(v):
    if not shape(v, 'stage failed before after events source'):
        return False
    failed, events, source = v['failed'], v['events'], v['source']
    return (v['stage'] in STAGES and isinstance(failed,list) and 0 < len(failed) <= len(CHECKS) and
        all(type(c) is str and c in CHECKS for c in failed) and len(set(failed)) == len(failed) and
        snapshot(v['before']) and snapshot(v['after']) and isinstance(events,list) and len(events) <= 16 and
        all(shape(e,'event at content zoom focused') and e['event'] in EVENTS and numeric(e['at']) and e['at'] >= 0 and
            numbers(e['content'],4) and nullable_number(e['zoom']) and nullable_bool(e['focused']) for e in events) and
        (source is None or shape(source,'matches width height empty') and type(source['matches']) is int and
            0 <= source['matches'] <= 1024 and nullable_number(source['width']) and nullable_number(source['height']) and nullable_bool(source['empty'])))
