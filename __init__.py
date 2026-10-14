"""ShantyCircuit YuE2 ABC helpers: ComfyUI nodes for working with YuE2 ABC scores.

Nodes (category: ShantyCircuit/YuE2):
  "SC YuE2 ABC Length Search" - reruns YuE2 Generate ABC until the score fits a target length
  "SC YuE2 ABC Song Length"   - reports a score's length, section by section (numbered)
  "SC YuE2 ABC Speed Change"  - speeds a whole score up or down by a percentage
  "SC YuE2 ABC Fix Meter"     - repairs one-bar meter glitches (e.g. a stray 7/8 or 9/8 bar)

Requires a recent ComfyUI with the V3 node API (comfy_api.latest) and the
built-in YuE2 nodes. Install by placing this folder in ComfyUI/custom_nodes/.
"""
import inspect
import itertools
import re
from collections import OrderedDict
from fractions import Fraction

from comfy_api.latest import ComfyExtension, io, ui

# Frontend script that shows each node's summary text on the node itself.
WEB_DIRECTORY = "./js"

# --------------------------------------------------------------------------
# Shared parsing helpers
# --------------------------------------------------------------------------

_Q_PATTERN = re.compile(r'^(\s*(?:"[^"]*"\s*)?(?:(\d+/\d+)\s*=\s*)?)(\d+(?:\.\d+)?)(.*)$')


def _fraction(text):
    num, den = text.strip().split("/")
    return Fraction(int(num), int(den))


def _parse_q(body):
    """Parse the text after 'Q:' into (beat unit, bpm). Handles 'Q:1/4=120' and 'Q:120'."""
    m = _Q_PATTERN.match(body)
    if not m:
        return None
    unit = _fraction(m.group(2)) if m.group(2) else Fraction(1, 4)
    return unit, float(m.group(3))


def _scale_q_body(body, factor, changes=None):
    """Rewrite the tempo number inside one Q: field, keeping its unit and any label."""
    m = _Q_PATTERN.match(body)
    if not m:
        return body
    old = float(m.group(3))
    new = max(1, round(old * factor))
    if changes is not None:
        changes.append((old, new))
    return f"{m.group(1)}{new}{m.group(4)}"


def _bars_in_line(line):
    """Return (bars, vocal-free bars) for one voice line."""
    total, empty = 0, 0
    for bar in line.strip().rstrip("|").split("|"):
        bar = re.sub(r'"[^"]*"', "", bar).strip()  # drop chord symbols
        bar = re.sub(r"\[[A-Za-z]:[^\]]*\]", "", bar).strip()  # drop inline fields
        multi = re.fullmatch(r"Z(\d*)", bar)
        if multi:
            n = int(multi.group(1) or 1)
            total += n
            empty += n
            continue
        total += 1
        if not re.search(r"[A-Ga-g]", bar):
            empty += 1
    return total, empty


def _is_section_marker(line):
    s = line.strip()
    return s.startswith("%") and not s.startswith("%%")


def _fmt(seconds):
    m, s = divmod(round(seconds), 60)
    return f"{m}:{s:02d}"


# --------------------------------------------------------------------------
# Length analysis
# --------------------------------------------------------------------------

def analyze_abc(text):
    """Return (sections, longest_gap, meter_text, tempo_unit, bpm).

    Each section is [name, bars, vocal_free_bars, seconds, bpm_at_start].
    Bars are counted from the Vocal voice only.
    """
    meter, meter_text = Fraction(4, 4), "4/4"
    tempo_unit, bpm = Fraction(1, 4), 120.0
    header_unit, header_bpm, header_done = None, None, False
    voice = None
    sections = []
    longest_gap = current_gap = 0

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("M:"):
            meter_text = line[2:].strip()
            meter = _fraction(meter_text)
            continue
        if line.startswith("Q:"):
            parsed = _parse_q(line[2:])
            if parsed:
                tempo_unit, bpm = parsed
                if not header_done:
                    header_unit, header_bpm = parsed
            continue
        if line.startswith(("X:", "T:", "L:", "K:")):
            continue
        if line.startswith("%") and not line.startswith("%%"):
            header_done = True
            sections.append([line.lstrip("% ").strip() or "section", 0, 0, 0.0, bpm])
            continue
        if line.startswith("V:"):
            voice = line[2:].split()[0]
            continue
        if voice != "Vocal":
            continue
        header_done = True
        if not sections:
            sections.append(["(start)", 0, 0, 0.0, bpm])
        if sections[-1][1] == 0:
            sections[-1][4] = bpm  # tempo in effect when the section's first bar plays

        # inline tempo changes inside a vocal line, e.g. [Q:1/4=120]
        pieces = re.split(r"\[Q:([^\]]*)\]", line)
        for idx, piece in enumerate(pieces):
            if idx % 2 == 1:
                parsed = _parse_q(piece)
                if parsed:
                    tempo_unit, bpm = parsed
                continue
            if not piece.strip().strip("|"):
                continue
            seconds_per_bar = float(meter / tempo_unit) * 60 / bpm
            total, empty = _bars_in_line(piece)
            sections[-1][1] += total
            sections[-1][2] += empty
            sections[-1][3] += total * seconds_per_bar
            for bar in piece.strip().rstrip("|").split("|"):
                if not bar.strip():
                    continue
                t, e = _bars_in_line(bar + "|")
                if e == t:
                    current_gap += t
                    longest_gap = max(longest_gap, current_gap)
                else:
                    current_gap = 0

    unit = header_unit if header_unit is not None else tempo_unit
    base = header_bpm if header_bpm is not None else bpm
    return sections, longest_gap, meter_text, unit, base


def build_report(text):
    sections, longest_gap, meter_text, unit, bpm = analyze_abc(text)
    if not sections:
        return "No bars found. Is this a YuE2 ABC score?", 0.0, 0

    lines = [f"Starting tempo {unit}={bpm:g}, meter {meter_text}",
             f"{'#':>2}  {'Section':<12}{'Tempo':>6}{'Bars':>6}{'No vox':>8}{'Length':>8}"]
    total_bars = total_empty = 0
    total_sec = 0.0
    for i, (name, bars, empty, sec, sec_bpm) in enumerate(sections, 1):
        flag = "  <- instrumental" if bars and empty / bars > 0.75 else ""
        lines.append(f"{i:>2}  {name[:12]:<12}{sec_bpm:>6g}{bars:>6}{empty:>8}{_fmt(sec):>8}{flag}")
        total_bars += bars
        total_empty += empty
        total_sec += sec
    lines.append("-" * 42)
    lines.append(f"{'':>2}  {'Total':<12}{'':>6}{total_bars:>6}{total_empty:>8}{_fmt(total_sec):>8}")
    lines.append(f"Longest stretch without vocals: {longest_gap} bars")
    lines.append(f"Total seconds: {total_sec:.2f}")
    for number, name, meter_text in find_meter_changes(text):
        lines.append(f"Warning: meter switches to {meter_text} in #{number} {name}"
                     f" (likely a glitch; SC YuE2 ABC Fix Meter can repair it)")
    return "\n".join(lines), total_sec, total_bars


# --------------------------------------------------------------------------
# Whole-score speed change
# --------------------------------------------------------------------------

def change_abc_speed(text, percent):
    """Speed the score up (positive percent) or down (negative percent)."""
    factor = 1 + percent / 100.0
    changes = []
    out = []
    for line in text.splitlines():
        if line.lstrip().startswith("Q:"):
            indent = line[: len(line) - len(line.lstrip())]
            body = line.lstrip()[2:]
            line = indent + "Q:" + _scale_q_body(body, factor, changes)
        else:
            line = re.sub(r"\[Q:([^\]]*)\]",
                          lambda m: "[Q:" + _scale_q_body(m.group(1), factor, changes) + "]",
                          line)
        out.append(line)
    if text.endswith("\n"):
        out.append("")
    return "\n".join(out), changes


# --------------------------------------------------------------------------
# Odd-meter glitches (a single bar that briefly switches meter)
# --------------------------------------------------------------------------

def _header_info(lines):
    """Return (first_body_line_index, base_meter, unit_length) from the header."""
    meter, unit = Fraction(4, 4), Fraction(1, 8)
    body_start = len(lines)
    for i, raw in enumerate(lines):
        s = raw.strip()
        if s.startswith("M:"):
            meter = _fraction(s[2:])
        elif s.startswith("L:"):
            unit = _fraction(s[2:])
        elif s.startswith("K:"):
            body_start = i + 1
            break
    return body_start, meter, unit


def _is_music_line(s):
    return bool(s) and not s.startswith(("%", "V:", "M:", "Q:", "L:", "K:", "X:", "T:"))


def _bar_count(s):
    return len([b for b in s.rstrip("|").split("|") if b.strip()])


def find_meter_changes(text):
    """List mid-score meter changes as (section_number, section_name, meter_text)."""
    lines = text.splitlines()
    body_start, base, _ = _header_info(lines)
    found, section, name, voice = [], 0, "(start)", None
    seen = set()
    for raw in lines[body_start:]:
        s = raw.strip()
        if _is_section_marker(s):
            section += 1
            name = s.lstrip("% ").strip() or "section"
        elif s.startswith("V:"):
            voice = s[2:].split()[0]
        elif s.startswith("M:") and voice == "Vocal":
            meter_text = s[2:].strip()
            if _fraction(meter_text) != base and (section, meter_text) not in seen:
                seen.add((section, meter_text))
                found.append((section, name, meter_text))
    return found


def _rest_total(bar):
    """Total length (in L units) of the rests inside one bar."""
    bar = re.sub(r'"[^"]*"', "", bar)
    return sum(int(m.group(1) or 1) for m in re.finditer(r"z(\d*)", bar))


def _pad_bar(line, amount):
    """Add a rest of `amount` units at the start of a one-bar line (after chord symbols)."""
    m = re.match(r'^(\s*(?:"[^"]*"\s*)*)(.*)$', line)
    return f"{m.group(1)}z{amount}{m.group(2)}"


def _trim_bar(line, amount):
    """Remove `amount` units of rest from a one-bar line, earliest rests first."""
    remaining = amount

    def shrink(m):
        nonlocal remaining
        length = int(m.group(1) or 1)
        if remaining <= 0:
            return m.group(0)
        cut = min(length, remaining)
        remaining -= cut
        left = length - cut
        return "" if left == 0 else (f"z{left}" if left != 1 else "z")

    # skip text inside chord symbols while editing rests
    parts = re.split(r'("[^"]*")', line)
    for i in range(0, len(parts), 2):
        parts[i] = re.sub(r"z(\d*)", shrink, parts[i])
    return "".join(parts)


def _plan_fix(bar_line, meter, base, unit):
    """Return ('pad'|'trim', units) if this one-bar line can be made a normal bar, else None."""
    if not _is_music_line(bar_line) or _bar_count(bar_line) != 1:
        return None
    body = re.sub(r'"[^"]*"', "", bar_line).strip().rstrip("|").strip()
    whole_bar_rest = bool(re.fullmatch(r"Z1?", body))
    diff = (base - meter) / unit
    if diff.denominator != 1:
        return None
    diff = int(diff)
    if diff > 0:
        return ("pad", diff)
    if diff < 0:
        if whole_bar_rest or _rest_total(bar_line) >= -diff:
            return ("trim", -diff)
        return None
    return None


def fix_meter_glitches(text):
    """Repair one-bar meter switches (a single bar briefly in a different meter).

    Shorter bars (e.g. 7/8 in 4/4) get a rest added at their start, so pickup
    notes at the end stay in place. Longer bars (e.g. 9/8 in 4/4) have the
    extra time removed from their rests, so no notes are lost. The meter-change
    lines around a repaired bar are removed. A glitch is only repaired if every
    voice's bar can be fixed, so the voices always stay lined up; otherwise it
    is left alone and reported as a warning.
    Returns (new_text, list_of_fixes, list_of_warnings).
    """
    lines = text.splitlines()
    body_start, base, unit = _header_info(lines)
    base_text = next((l.strip()[2:].strip() for l in lines[:body_start]
                      if l.strip().startswith("M:")), "4/4")

    # Pass 1: decide which glitches are fixable in every voice.
    plans = {}        # line index of an M: line -> ('pad'|'trim', units) or None
    group_ok = {}     # (section, meter text) -> True only if all voices are fixable
    section = 0
    for idx in range(body_start, len(lines)):
        s = lines[idx].strip()
        if _is_section_marker(s):
            section += 1
        elif s.startswith("M:"):
            meter = _fraction(s[2:])
            if meter == base:
                continue
            nxt = next((l.strip() for l in lines[idx + 1:] if l.strip()
                        and not l.strip().startswith(("Q:", "M:"))), "")
            plan = _plan_fix(nxt, meter, base, unit)
            plans[idx] = (section, s[2:].strip(), plan)
            key = (section, s[2:].strip())
            group_ok[key] = group_ok.get(key, True) and plan is not None

    # Pass 2: apply the fixes.
    out = lines[:body_start]
    fixes, warnings = [], []
    effective = {}     # voice -> meter currently in effect in the output
    pending = {}       # voice -> ('pad'|'trim', units) for its next bar
    voice, section, name = None, 0, "(start)"

    for idx in range(body_start, len(lines)):
        raw = lines[idx]
        s = raw.strip()
        if _is_section_marker(s):
            section += 1
            name = s.lstrip("% ").strip() or "section"
            out.append(raw)
            continue
        if s.startswith("V:"):
            voice = s[2:].split()[0]
            out.append(raw)
            continue
        if s.startswith("M:"):
            meter = _fraction(s[2:])
            current = effective.get(voice, base)
            if meter == base:
                if current == base:
                    continue  # redundant switch back to the main meter
                effective[voice] = base
                out.append(raw)
                continue
            sec, meter_text, plan = plans[idx]
            if group_ok[(sec, meter_text)]:
                pending[voice] = plan
                if voice == "Vocal":
                    how = ("with a rest added at its start" if plan[0] == "pad"
                           else "by shortening its rests")
                    fixes.append(f"#{section} {name}: one {meter_text} bar made {base_text} {how}")
                continue
            if voice == "Vocal":
                warnings.append(f"#{section} {name}: {meter_text} bar left as is "
                                f"(not enough rest to trim without cutting notes)")
            effective[voice] = meter
            out.append(raw)
            continue
        if voice in pending and _is_music_line(s):
            kind, units = pending.pop(voice)
            body = re.sub(r'"[^"]*"', "", raw).strip().rstrip("|").strip()
            if not re.fullmatch(r"Z1?", body):  # Z already fills any bar
                raw = _pad_bar(raw, units) if kind == "pad" else _trim_bar(raw, units)
            out.append(raw)
            continue
        out.append(raw)

    result = "\n".join(out)
    if text.endswith("\n"):
        result += "\n"
    return result, fixes, warnings


# --------------------------------------------------------------------------
# Nodes
# --------------------------------------------------------------------------

def _length_summary(text):
    """Short text shown on the YuE2 ABC Song Length node itself."""
    sections, longest_gap, meter_text, unit, bpm = analyze_abc(text)
    seconds = sum(s[3] for s in sections)
    bars = sum(s[1] for s in sections)
    empty = sum(s[2] for s in sections)
    lines = [
        f"Length: {_fmt(seconds)}  ({seconds:.2f} s)",
        f"Bars: {bars}  ({empty} without vocals, longest gap {longest_gap})",
        f"Tempo: {unit}={bpm:g}, meter {meter_text}",
    ]
    for number, name, meter in find_meter_changes(text):
        lines.append(f"Warning: {meter} bar in #{number} {name} (run SC YuE2 ABC Fix Meter)")
    return "\n".join(lines)


class ABCSongLength(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SC_YuE2ABCSongLength",
            display_name="SC YuE2 ABC Song Length",
            category="ShantyCircuit/YuE2",
            description="Reports how long a YuE2 ABC score will play, section by section. "
                        "Shows the totals on the node; the outputs can still be wired elsewhere.",
            is_output_node=True,  # adds a run button so the length can be checked on its own
            inputs=[
                io.String.Input("abc", force_input=True, optional=True),
            ],
            outputs=[
                io.String.Output(display_name="report"),
                io.Float.Output(display_name="seconds"),
                io.Int.Output(display_name="bars"),
            ],
        )

    @classmethod
    def execute(cls, abc=None) -> io.NodeOutput:
        if not abc or not abc.strip():
            message = "No ABC connected."
            return io.NodeOutput(message, 0.0, 0, ui=ui.PreviewText(message))
        report, seconds, bars = build_report(abc)
        seconds = round(float(seconds), 2)
        print("[SC YuE2 ABC Song Length]\n" + report)
        return io.NodeOutput(report, seconds, int(bars), ui=ui.PreviewText(_length_summary(abc)))


def _speed_factor(percent):
    """Tempo multiplier for a speed percent, with speed-ups and slow-downs as mirror images.

    +100 -> 2x (twice as fast), -100 -> 1/2x (half speed)
    +200 -> 3x,                 -200 -> 1/3x
    """
    percent = float(percent)
    if percent >= 0:
        return 1.0 + percent / 100.0
    return 1.0 / (1.0 + abs(percent) / 100.0)


class ABCSpeedChange(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SC_YuE2ABCSpeedChange",
            display_name="SC YuE2 ABC Speed Change",
            category="ShantyCircuit/YuE2",
            description="Speeds a whole ABC score up (positive percent) or down (negative percent) "
                        "by scaling its tempo. Positive and negative are mirror images: +100 doubles "
                        "the tempo and -100 halves it. Notes and bars are unchanged.",
            inputs=[
                io.Float.Input("speed_percent", default=10.0, min=-200.0, max=200.0, step=1.0,
                               tooltip="Positive = faster, negative = slower, symmetrically: +100 is twice "
                                       "as fast and -100 is half speed; +200 is three times as fast and "
                                       "-200 is one third of the speed."),
                io.String.Input("abc", force_input=True, optional=True),
            ],
            outputs=[
                io.String.Output(display_name="abc"),
                io.String.Output(display_name="report"),
                io.Float.Output(display_name="seconds"),
            ],
        )

    @classmethod
    def execute(cls, speed_percent, abc=None) -> io.NodeOutput:
        if not abc or not abc.strip():
            message = "No ABC connected."
            return io.NodeOutput("", message, 0.0, ui=ui.PreviewText(message))
        factor = _speed_factor(speed_percent)
        new_abc, changes = change_abc_speed(abc, (factor - 1.0) * 100.0)
        if not changes:
            message = "No Q: tempo line found, so the score was left unchanged."
            return io.NodeOutput(abc, message, 0.0, ui=ui.PreviewText(message))
        _, old_seconds, _ = build_report(abc)
        report, new_seconds, _ = build_report(new_abc)
        unique = list(dict.fromkeys(changes))  # each tempo change listed once
        tempo_lines = ", ".join(f"{o:g} -> {n:g}" for o, n in unique)
        summary = (f"Speed {speed_percent:+g}% ({factor:.2f}x): tempo {tempo_lines}\n"
                   f"Length {_fmt(old_seconds)} -> {_fmt(new_seconds)}")
        print("[SC YuE2 ABC Speed Change]\n" + summary + "\n\n" + report)
        return io.NodeOutput(new_abc, summary + "\n\n" + report, float(new_seconds),
                             ui=ui.PreviewText(summary))


class ABCFixMeter(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SC_YuE2ABCFixMeter",
            display_name="SC YuE2 ABC Fix Meter",
            category="ShantyCircuit/YuE2",
            description="Repairs one-bar meter glitches (such as a stray 7/8 or 9/8 bar in a 4/4 song) "
                        "by adding or trimming rest. Scores without glitches pass through unchanged.",
            inputs=[
                io.String.Input("abc", force_input=True, optional=True),
            ],
            outputs=[
                io.String.Output(display_name="abc"),
                io.String.Output(display_name="report"),
            ],
        )

    @classmethod
    def execute(cls, abc=None) -> io.NodeOutput:
        if not abc or not abc.strip():
            message = "No ABC connected."
            return io.NodeOutput("", message, ui=ui.PreviewText(message))
        new_abc, fixes, warnings = fix_meter_glitches(abc)
        lines = fixes or ["No meter glitches found; the score is unchanged."]
        lines += [f"Warning: {w}" for w in warnings]
        report = "\n".join(lines)
        print("[SC YuE2 ABC Fix Meter]\n" + report)
        return io.NodeOutput(new_abc, report, ui=ui.PreviewText(report))


# --------------------------------------------------------------------------
# Generate-until-length: reruns the built-in YuE2 Generate ABC node
# --------------------------------------------------------------------------

try:  # lets the node skip downstream nodes (the render) when no score fits
    from comfy_execution.graph_utils import ExecutionBlocker
except ImportError:
    try:
        from comfy_execution.graph import ExecutionBlocker
    except ImportError:
        ExecutionBlocker = None

# Seeds stay below 2^53 so the browser can store them exactly (larger whole
# numbers get rounded in JavaScript, which would silently change the seed).
_MAX_SEED = 2 ** 53 - 1

# Scores already generated in this session, keyed by everything that affects
# generation. Re-running a seed that was already tried is then instant.
_GENERATED = OrderedDict()
_GENERATED_LIMIT = 256

# Most recent attempts listed on the node (long searches would otherwise flood it).
_LOG_LINES = 15


def _score_seconds(text):
    return sum(section[3] for section in analyze_abc(text)[0])


LIVE_EVENT = "shantycircuit.yue2_abc.progress"


def _send_live_status(node_id, text):
    """Push interim text to the node's display box while a long search runs."""
    if node_id is None:
        return
    try:
        from server import PromptServer
        PromptServer.instance.send_sync(LIVE_EVENT, {"node": str(node_id), "text": text})
    except Exception:
        pass  # no server (or an older one): the console log still shows progress


def _check_interrupted():
    """Stop between attempts if the user pressed Cancel in ComfyUI."""
    try:
        import comfy.model_management as model_management
        model_management.throw_exception_if_processing_interrupted()
    except ImportError:
        pass


async def _generate_core_abc(**kwargs):
    """Run ComfyUI's built-in YuE2 Generate ABC node once and return its ABC text."""
    import nodes
    node_cls = nodes.NODE_CLASS_MAPPINGS.get("YuE2GenerateABC")
    if node_cls is None:
        raise RuntimeError("The built-in 'YuE2GenerateABC' node was not found. "
                           "Update ComfyUI to a version that includes YuE2.")
    if hasattr(node_cls, "FUNCTION"):            # older node style
        out = getattr(node_cls(), node_cls.FUNCTION)(**kwargs)
    else:                                         # V3 node style
        out = node_cls.execute(**kwargs)
    if inspect.isawaitable(out):
        out = await out

    values = None
    for attr in ("result", "args"):
        candidate = getattr(out, attr, None)
        if candidate:
            values = candidate
            break
    if values is None:
        if isinstance(out, dict):
            values = out.get("result")
        elif isinstance(out, (tuple, list)):
            values = out
    if not values or not isinstance(values[0], str):
        raise RuntimeError(f"Unexpected output from YuE2GenerateABC: {type(out).__name__}")
    return values[0]


def _window_distance(seconds, low, high):
    """0 inside the accepted window, otherwise how far outside it the length is."""
    if seconds < low:
        return low - seconds
    if seconds > high:
        return seconds - high
    return 0.0


def _tempo_words(percent):
    """'sped up 8%' / 'slowed down 6%' for a tempo change in percent."""
    return f"{'sped up' if percent > 0 else 'slowed down'} {abs(percent):.0f}%"


def _fit_to_window(abc, low, high, max_tempo_change):
    """Nudge the tempo toward [low, high], by at most |max_tempo_change| percent.

    The direction is chosen automatically: a score that's too long is sped up,
    one that's too short is slowed down. The sign of max_tempo_change doesn't
    matter (10 and -10 both allow up to 10% either way). If the full change
    needed is larger than allowed, the score still moves as far toward the
    target as allowed. The score is otherwise left exactly as generated.

    Returns (abc, seconds, tempo_percent_applied, original_seconds, (old_bpm, new_bpm) or None).
    """
    original = _score_seconds(abc)
    allowed = abs(float(max_tempo_change))
    if original <= 0 or allowed == 0 or low <= original <= high:
        return abc, original, 0.0, original, None
    aim = (low + high) / 2.0                         # middle of the window leaves margin both ways
    needed = (original / aim - 1.0) * 100.0          # + speeds up a long score, - slows a short one
    percent = max(-allowed, min(allowed, needed))
    adjusted, changes = change_abc_speed(abc, percent)
    if not changes:
        return abc, original, 0.0, original, None
    seconds = _score_seconds(adjusted)
    # keep the tempo change only if it brings the song closer to the window
    if _window_distance(seconds, low, high) < _window_distance(original, low, high):
        old_bpm, new_bpm = changes[0]
        actual = (new_bpm / old_bpm - 1.0) * 100.0   # after rounding the tempo to a whole number
        return adjusted, seconds, actual, original, (old_bpm, new_bpm)
    return abc, original, 0.0, original, None


class ABCGenerateToLength(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SC_YuE2ABCLengthSearch",
            display_name="SC YuE2 ABC Length Search",
            category="ShantyCircuit/YuE2",
            is_output_node=True,  # run button: search for a score without rendering audio
            hidden=[io.Hidden.unique_id],  # used to show live progress on the node
            description="Runs the built-in YuE2 Generate ABC node repeatedly, trying the next seed each time, "
                        "until the score's length lands within the accepted range around the target "
                        "(upper_t_seconds above it, lower_t_seconds below it). "
                        "The tempo can be nudged slightly to land closer to the target. Scores are otherwise "
                        "passed on as generated; if the chosen score has a meter glitch, the node says so "
                        "(SC YuE2 ABC Fix Meter can repair it). "
                        "If no attempt fits, it can stop the workflow or pass on the closest score. After a "
                        "successful run, the seed box is set to the winning seed, so queueing again reuses that "
                        "exact score; after a failed run, it moves past the seeds already tried.",
            inputs=[
                io.Clip.Input("clip"),
                io.String.Input("style", multiline=True, default=""),
                io.String.Input("lyrics", multiline=True, default=""),
                io.Int.Input("seed", default=0, min=0, max=_MAX_SEED,
                             control_after_generate=False,
                             tooltip="Seed the search starts from. After each run it is set to the "
                                     "seed of the chosen score, so queueing again reuses that score. "
                                     "Use the 'new search' button to start from a fresh seed."),
                io.Boolean.Input("new_seed_each_run", default=False,
                                 tooltip="Pick a random starting seed every time the workflow is queued. "
                                         "Turn off to reuse the last winning score."),
                io.Combo.Input("mode", options=["full", "melody"], default="full"),
                io.Int.Input("target_minutes", default=3, min=0, max=15,
                             tooltip="Target length (minutes part)."),
                io.Int.Input("target_seconds", default=30, min=0, max=59,
                             tooltip="Target length (seconds part)."),
                io.Float.Input("upper_t_seconds", default=10.0, min=0.0, max=120.0, step=1.0,
                               tooltip="How far over the target is still acceptable. "
                                       "0 = the target is a hard ceiling."),
                io.Float.Input("lower_t_seconds", default=10.0, min=0.0, max=120.0, step=1.0,
                               tooltip="How far under the target is still acceptable."),
                io.Int.Input("max_attempts", default=5, min=0, max=1000,
                             tooltip="Each attempt generates a new score with the next seed. "
                                     "0 = keep trying until a score fits (press Cancel to stop)."),
                io.Float.Input("max_tempo_change_percent", default=0.0, min=-30.0, max=30.0, step=1.0,
                               tooltip="How much the tempo may change to bring a near miss toward the target. "
                                       "The direction is automatic: scores that are too long are sped up, too "
                                       "short ones are slowed down. The sign doesn't matter (10 and -10 both "
                                       "allow up to 10% either way). 0 = never change the tempo."),
                io.Combo.Input("on_failure", options=["stop workflow", "use closest"], default="stop workflow",
                               tooltip="If no attempt fits: 'stop workflow' skips the nodes that use the abc "
                                       "output (no render); 'use closest' passes on the closest score anyway."),
                io.Int.Input("max_abc_tokens", default=8192, min=1, max=20000, advanced=True),
                io.Float.Input("temperature", default=0.7, min=0.0, max=5.0, step=0.01, advanced=True),
                io.Float.Input("top_p", default=0.9, min=0.01, max=1.0, step=0.01, advanced=True),
                io.Int.Input("top_k", default=30, min=1, max=32768, advanced=True),
                io.Float.Input("repetition_penalty", default=1.005, min=0.01, max=10.0, step=0.001,
                               advanced=True),
                io.Int.Input("penalty_window", default=100, min=1, max=20000, advanced=True),
            ],
            outputs=[
                io.String.Output(display_name="abc"),
                io.String.Output(display_name="report"),
                io.Float.Output(display_name="seconds"),
                io.Int.Output(display_name="seed_used"),
            ],
        )

    @classmethod
    async def execute(cls, clip, style, lyrics, seed, new_seed_each_run, mode, target_minutes, target_seconds,
                      upper_t_seconds, lower_t_seconds,
                      max_attempts, max_tempo_change_percent, on_failure, max_abc_tokens,
                      temperature, top_p, top_k, repetition_penalty, penalty_window) -> io.NodeOutput:
        target = int(target_minutes) * 60 + int(target_seconds)
        if target <= 0:
            raise ValueError("Set a target length above 0:00.")
        high = float(target) + float(upper_t_seconds)
        low = max(0.0, float(target) - float(lower_t_seconds))
        header = f"Target {_fmt(target)} (accepting {_fmt(low)} to {_fmt(high)})"
        unlimited = int(max_attempts) == 0
        if unlimited:
            header += ", trying until one fits"
        log = []     # one line per attempt
        best = None  # (rank, abc, seconds, seed, tempo_percent)
        found = False
        tried = 0
        node_id = getattr(getattr(cls, "hidden", None), "unique_id", None)

        attempts = itertools.count() if unlimited else range(int(max_attempts))
        _send_live_status(node_id, f"Searching from seed {int(seed)}...\n{header}")
        for attempt in attempts:
            _check_interrupted()
            try_seed = (int(seed) + attempt) % (_MAX_SEED + 1)
            tried = attempt + 1
            key = (id(clip), style, lyrics, mode, try_seed, max_abc_tokens, temperature,
                   top_p, top_k, repetition_penalty, penalty_window)
            cached = key in _GENERATED
            if cached:
                raw = _GENERATED[key]
                _GENERATED.move_to_end(key)
            else:
                raw = await _generate_core_abc(
                    clip=clip, style=style, lyrics=lyrics, seed=try_seed, mode=mode,
                    max_abc_tokens=max_abc_tokens, temperature=temperature, top_p=top_p,
                    top_k=top_k, repetition_penalty=repetition_penalty, penalty_window=penalty_window,
                )
                _GENERATED[key] = raw
                while len(_GENERATED) > _GENERATED_LIMIT:
                    _GENERATED.popitem(last=False)
            abc, seconds, tempo, original, bpms = _fit_to_window(
                raw, low, high, float(max_tempo_change_percent))
            distance = _window_distance(seconds, low, high)
            ok = distance == 0
            note = f" ({_tempo_words(tempo)} from {_fmt(original)})" if tempo else ""
            log.append(f"#{attempt + 1} seed {try_seed}: {_fmt(seconds)}{note}  "
                       f"{'fits' if ok else 'too ' + ('long' if seconds > high else 'short')}"
                       f"{'  (reused)' if cached else ''}")
            print(f"[SC YuE2 ABC Length Search] {log[-1]}")
            recent = log[-_LOG_LINES:]
            _send_live_status(node_id, "\n".join([f"Searching... attempt {tried}", header] + recent))
            # Prefer scores that aren't over the range; among those, the closest to it.
            rank = (seconds > high, distance)
            if best is None or rank < best[0]:
                best = (rank, abc, seconds, try_seed, tempo, bpms)
            if ok:
                found = True
                break

        _, abc, seconds, used_seed, tempo, bpms = best
        next_seed = (int(seed) + tried) % (_MAX_SEED + 1)
        stop = not found and on_failure == "stop workflow"
        notes = []
        if found:
            status = f"FOUND: seed {used_seed}, {_fmt(seconds)} (attempt {tried})"
            box_seed = used_seed           # queue again to reuse this exact score
        else:
            status = f"NOT FOUND after {tried} attempt{'s' if tried != 1 else ''}"
            box_seed = next_seed           # run again to keep searching with new seeds
            if stop:
                notes.append(f"Workflow stopped (closest was seed {used_seed}, {_fmt(seconds)}).")
            elif seconds <= high:
                notes.append(f"Using the closest that isn't too long, seed {used_seed}: {_fmt(seconds)}")
            else:
                notes.append(f"Using the closest, seed {used_seed}: {_fmt(seconds)} "
                             f"(longer than the accepted range)")
            notes.append(f"Seed box moved to {next_seed} to continue the search.")
        shown = log
        if len(log) > _LOG_LINES:
            shown = [f"({len(log) - _LOG_LINES} earlier attempts not shown)"] + log[-_LOG_LINES:]
        if tempo and bpms:
            notes.append(f"Tempo {bpms[0]:g} -> {bpms[1]:g} bpm ({_tempo_words(tempo)}) for seed {used_seed}.")
        # Meter glitches are only reported for the score actually chosen (found or closest).
        for number, name, meter in find_meter_changes(abc):
            notes.append(f"Warning: seed {used_seed} has a {meter} bar in #{number} {name} "
                         f"(run SC YuE2 ABC Fix Meter)")
        summary = "\n".join([status, header] + shown + notes)
        report, _, _ = build_report(abc)
        full_report = summary + "\n\n" + report
        ui_data = {"text": [summary], "next_seed": [int(box_seed)], "found": [bool(found)]}
        abc_out = abc
        if stop:
            message = (f"SC YuE2 ABC Length Search: no score fit {_fmt(low)} to {_fmt(high)} "
                       f"in {tried} attempts, so the render was skipped.")
            if ExecutionBlocker is None:
                raise RuntimeError(message)
            abc_out = ExecutionBlocker(message)
        return io.NodeOutput(abc_out, full_report, round(float(seconds), 2), int(used_seed), ui=ui_data)


class ShantyCircuitYuE2ABC(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [ABCGenerateToLength, ABCSongLength, ABCSpeedChange, ABCFixMeter]


async def comfy_entrypoint() -> ShantyCircuitYuE2ABC:
    return ShantyCircuitYuE2ABC()
