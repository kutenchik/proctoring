"""Small target lists for the existing diagnostic collector, not exam state."""
from copy import deepcopy

TRAINING_PROTOCOL = "screen_region_training_v1"


def _point(identity, x, y, instruction, *, anchor=None):
    value = {"id": identity, "role": "on_screen_calibration", "expected_label": "ON_SCREEN",
             "instruction": instruction, "position_kind": "screen",
             "requested_position": {"x_normalized": x, "y_normalized": y}}
    if anchor:
        value["anchor"] = anchor
    return value


def training_specs():
    targets = [
        _point("CENTER_START", .5, .5, "Fixate the marker at the physical screen center.", anchor="start"),
        _point("SCREEN_LEFT", .08, .5, "Fixate the marker inside the left screen area."),
        _point("SCREEN_RIGHT", .92, .5, "Fixate the marker inside the right screen area."),
        _point("SCREEN_UPPER", .5, .10, "Fixate the marker inside the upper screen area."),
        _point("SCREEN_LOWER", .5, .88, "Fixate the marker inside the lower screen area."),
    ]
    for identity, widget in (("QUIZ", "quiz"), ("OPTIONS", "options"),
                             ("CONTROLS", "controls"), ("MONITOR", "monitor")):
        targets.append({"id": identity, "role": "on_screen_calibration", "expected_label": "ON_SCREEN",
                        "position_kind": "widget", "widget_anchor": widget,
                        "instruction": f"Fixate the marker on the actual {widget} area."})
    for direction in ("LEFT", "RIGHT", "DOWN"):
        edge = {"LEFT": "left", "RIGHT": "right", "DOWN": "bottom"}[direction]
        targets.append({"id": f"OFF_{direction}", "role": "off_screen_calibration",
                        "expected_label": direction, "position_kind": "physical_off_screen",
                        "position": {"kind": "operator_physical_target", "direction": direction,
                                     "coordinate_status": "physical location not measured"},
                        "instruction": f"Fixate your repeatable physical marker just beyond the {edge} screen edge. "
                                       "Use the same marker in validation; keep your head comfortable."})
    targets.append(_point("CENTER_END", .5, .5, "Return to the same physical screen center marker.", anchor="end"))
    return targets


def validation_specs():
    source = {target["id"]: target for target in training_specs()}
    targets = []
    for key in ("CENTER_START", "SCREEN_LEFT", "SCREEN_RIGHT", "SCREEN_UPPER", "SCREEN_LOWER"):
        value = deepcopy(source[key])
        value.update(id="VALIDATE_" + key, role="held_out_validation", source_training_id=key)
        value.pop("anchor", None)
        targets.append(value)
    for repeat in (1, 2):
        targets.append({"id": f"READING_{repeat}", "role": "held_out_validation",
                        "expected_label": "ON_SCREEN", "position_kind": "reading",
                        "instruction": "Read the real quiz question and answer choices naturally across the allowed layout."})
        for direction in ("LEFT", "RIGHT", "DOWN"):
            value = deepcopy(source[f"OFF_{direction}"])
            value.update(id=f"{direction}_{repeat}", role="held_out_validation",
                         source_training_id=f"OFF_{direction}")
            targets.append(value)
    for identity, instruction in (
        ("BLINK", "Look at screen center, blinking ordinarily during the middle interval."),
        ("BRIEF_CLOSURE", "Briefly close and reopen your eyes when prompted; otherwise look at screen center."),
        ("SUSTAINED_CLOSURE", "Keep both eyes gently closed throughout the collection interval."),
        ("SQUINT", "Gently squint while still looking at the physical screen center; do not look down."),
    ):
        value = deepcopy(source["CENTER_START"])
        value.update(id=identity, role="held_out_validation", instruction=instruction,
                     expected_label="ON_SCREEN" if identity == "SQUINT" else None)
        value.pop("anchor", None)
        # Intentional phase labels are operator instructions, not an automatic
        # blink detector. Mixed transitions are unscored, never default UNKNOWN.
        if identity == "BLINK":
            value["phases"] = [
                {"start_fraction": 0., "end_fraction": 1/3, "expected_label": "ON_SCREEN", "instruction": "Eyes open; look at screen center."},
                {"start_fraction": 1/3, "end_fraction": 2/3, "expected_label": None, "instruction": "Blink ordinarily while looking at screen center."},
                {"start_fraction": 2/3, "end_fraction": 1., "expected_label": "ON_SCREEN", "instruction": "Eyes open again; look at screen center."},
            ]
        elif identity == "BRIEF_CLOSURE":
            value["phases"] = [
                {"start_fraction": 0., "end_fraction": 1/3, "expected_label": "ON_SCREEN", "instruction": "Eyes open; look at screen center."},
                {"start_fraction": 1/3, "end_fraction": .5, "expected_label": None, "instruction": "Briefly close both eyes now."},
                {"start_fraction": .5, "end_fraction": 2/3, "expected_label": None, "instruction": "Reopen your eyes now; allow the transition."},
                {"start_fraction": 2/3, "end_fraction": 1., "expected_label": "ON_SCREEN", "instruction": "Eyes open; look at screen center."},
            ]
        targets.append(value)
    return targets


def phase_at(spec, fraction):
    for phase in spec.get("phases", ()):
        if phase["start_fraction"] <= fraction < phase["end_fraction"]:
            return phase
    return {"expected_label": spec.get("expected_label"), "instruction": spec["instruction"]}
