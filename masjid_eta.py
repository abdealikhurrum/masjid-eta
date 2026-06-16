#!/usr/bin/env python3
"""masjid-eta — predicted driving times to a destination for a target arrival time.

Reads a JSON config (destination, arrival time, timezone, origins) so you can
point it at any address and any set of starting points without touching code.
Uses the Google Routes API (computeRoutes) with TRAFFIC_AWARE_OPTIMAL, so times
reflect *predicted* traffic for the target morning rather than free-flow.

Setup:
    pip install requests
    export GMAPS_API_KEY=your_key_here     # Routes API must be enabled on the key
    cp config.example.json config.json     # then edit config.json

Usage:
    python masjid_eta.py                 # next occurrence of today's weekday
    python masjid_eta.py sat             # next Saturday
    python masjid_eta.py 2026-06-20      # a specific date
    python masjid_eta.py now             # live traffic right now (projected arrival)

    -w / --whatsapp   WhatsApp-ready text (copy-paste)
    -p / --preview    open a formatted WhatsApp-style preview in the browser
    -c / --config P   use config file P (default: config.json beside this script)
    -a / --arrive T   override target arrival time, e.g. 19:00, 7pm, 9:45am
"""

import os
import sys
import json
import datetime as dt
from zoneinfo import ZoneInfo

import requests

API_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

WEEKDAYS = {
    "mon": 0, "monday": 0, "tue": 1, "tues": 1, "tuesday": 1,
    "wed": 2, "wednesday": 2, "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
    "fri": 4, "friday": 4, "sat": 5, "saturday": 5, "sun": 6, "sunday": 6,
}

LEVEL_EMOJI = {"heavy": "🔴", "moderate": "🟠", "light": "🟢", "": ""}


def parse_clock(s):
    """Parse a time like '19:00', '7pm', '9:45am', '9' into (hour, minute)."""
    t = s.strip().lower().replace(" ", "")
    ampm = None
    if t.endswith("am"):
        ampm, t = "am", t[:-2]
    elif t.endswith("pm"):
        ampm, t = "pm", t[:-2]
    try:
        hh, mm = (t.split(":") + ["0"])[:2]
        hh, mm = int(hh), int(mm)
    except ValueError:
        raise ValueError(f"could not parse time '{s}' (try 19:00, 7pm, 9:45am)")
    if ampm == "pm" and hh != 12:
        hh += 12
    if ampm == "am" and hh == 12:
        hh = 0
    if not (0 <= hh < 24 and 0 <= mm < 60):
        raise ValueError(f"time out of range: '{s}'")
    return hh, mm

DISCLAIMER = ("Point-in-time estimate from Google Maps APIs. Actual traffic and "
              "travel times will vary — no guarantees.")


# --- Config --------------------------------------------------------------

class Config:
    def __init__(self, data):
        self.name = data.get("name", "Masjid ETA")
        self.emoji = data.get("emoji", "🕌")
        self.destination = data["destination"]            # address or {lat,lng}
        self.tz = ZoneInfo(data.get("timezone", "America/Chicago"))
        hh, mm = (data.get("arrive", "09:45")).split(":")
        self.arrive_hour, self.arrive_min = int(hh), int(mm)
        if not data.get("origins"):
            raise ValueError("config needs at least one entry in 'origins'")
        self.origins = data["origins"]                    # name -> address or {lat,lng}

    @property
    def arrive_str(self):
        t = dt.time(self.arrive_hour, self.arrive_min)
        return t.strftime("%-I:%M %p")


def load_config(path):
    if not os.path.exists(path):
        sys.exit(f"Config not found: {path}\n"
                 f"Copy config.example.json to config.json and edit it.")
    with open(path, encoding="utf-8") as f:
        try:
            return Config(json.load(f))
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            sys.exit(f"Bad config ({path}): {e}")


def waypoint(loc):
    """Build a Routes API waypoint from an address string or a {lat,lng} dict."""
    if isinstance(loc, str):
        return {"address": loc}
    if isinstance(loc, dict) and "lat" in loc and "lng" in loc:
        return {"location": {"latLng": {
            "latitude": loc["lat"], "longitude": loc["lng"]}}}
    raise ValueError(f"location must be an address string or {{lat,lng}}: {loc!r}")


# --- Date handling -------------------------------------------------------

def resolve_arrival(arg, now, cfg):
    """Return a tz-aware arrival datetime for the requested day."""
    def at_time(d):
        return dt.datetime(d.year, d.month, d.day,
                           cfg.arrive_hour, cfg.arrive_min, tzinfo=cfg.tz)

    if arg is None:
        cand = at_time(now.date())
        if cand <= now:
            cand += dt.timedelta(days=7)
        return cand

    key = arg.strip().lower()
    if key in WEEKDAYS:
        days = (WEEKDAYS[key] - now.weekday()) % 7
        cand = at_time(now.date() + dt.timedelta(days=days))
        if cand <= now:
            cand += dt.timedelta(days=7)
        return cand

    try:
        d = dt.date.fromisoformat(arg)
    except ValueError:
        sys.exit(f"Could not parse '{arg}'. Use: a weekday (sat), YYYY-MM-DD, or now.")
    cand = at_time(d)
    if cand <= now:
        sys.exit(f"{cand:%a %b %d %-I:%M %p} is in the past — pick a future date.")
    return cand


# --- Routes API ----------------------------------------------------------

def _route_duration(api_key, origin_wp, dest_wp, departure_utc=None, traffic=True):
    body = {
        "origin": origin_wp,
        "destination": dest_wp,
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE_OPTIMAL" if traffic else "TRAFFIC_UNAWARE",
    }
    if departure_utc is not None:
        body["departureTime"] = departure_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    fields = "routes.duration,routes.distanceMeters" if traffic else "routes.duration"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": fields,
    }
    r = requests.post(API_URL, json=body, headers=headers, timeout=20)
    r.raise_for_status()
    routes = r.json().get("routes")
    if not routes:
        raise RuntimeError("no route returned")
    secs = int(routes[0]["duration"].rstrip("s"))
    meters = routes[0].get("distanceMeters", 0)
    return secs, meters


def drive_duration(api_key, origin_wp, dest_wp, departure_utc):
    return _route_duration(api_key, origin_wp, dest_wp, departure_utc, traffic=True)


def freeflow_seconds(api_key, origin_wp, dest_wp):
    return _route_duration(api_key, origin_wp, dest_wp, None, traffic=False)[0]


def leave_by(api_key, origin_wp, dest_wp, arrival, now):
    """Fixed-point iteration: find a departure so departure + traffic_duration ~ arrival.

    Google driving routes take a departure time, not an arrival time, so we
    converge on it. Returns (duration_seconds, leave_dt, meters, late_flag).
    """
    tz = arrival.tzinfo
    arrival_utc = arrival.astimezone(dt.timezone.utc)
    now_utc = now.astimezone(dt.timezone.utc)
    dur = 1800  # initial guess: 30 min
    meters = 0
    late = False
    for _ in range(5):
        departure = arrival_utc - dt.timedelta(seconds=dur)
        if departure <= now_utc:
            departure = now_utc + dt.timedelta(seconds=60)
            late = True
        new_dur, meters = drive_duration(api_key, origin_wp, dest_wp, departure)
        if abs(new_dur - dur) < 60:
            dur = new_dur
            break
        dur = new_dur
    leave = (arrival_utc - dt.timedelta(seconds=dur)).astimezone(tz)
    if leave <= now:
        late = True
    return dur, leave, meters, late


def traffic_level(dur, freeflow):
    """Classify congestion from the gap between traffic-aware and free-flow times."""
    if not freeflow:
        return ""
    extra = dur - freeflow
    ratio = dur / freeflow
    if extra >= 600 or (ratio >= 1.5 and extra >= 300):
        return "heavy"
    if extra >= 300 or (ratio >= 1.25 and extra >= 180):
        return "moderate"
    return "light"


# --- Output --------------------------------------------------------------

def print_table(cfg, title, time_label, rows):
    dest = cfg.destination if isinstance(cfg.destination, str) else "destination"
    print(f"\n{cfg.name} — {title} ({dest})\n")
    print(f"{'Origin':<15}{'Drive':>8}{time_label:>12}{'Miles':>8}  Traffic")
    print("-" * 54)
    for name, dur, when, miles, late, level, err in rows:
        if err:
            print(f"{name:<15}{'error':>8}   {err}")
            continue
        mins = round(dur / 60)
        when_str = when.strftime("%-I:%M %p")
        traffic = f"  {LEVEL_EMOJI[level]} {level}" if level else ""
        flag = "  ⚠ leave now" if late else ""
        print(f"{name:<15}{mins:>5} m{when_str:>12}{miles:>8.1f}{traffic}{flag}")
    print("\n🟢 light   🟠 moderate   🔴 heavy   (vs. free-flow time)")
    print(f"\n{DISCLAIMER}\n")


def whatsapp_text(cfg, title, time_label, rows):
    """Copy-paste-ready message. Uses WhatsApp *bold*; no tables (break on mobile)."""
    verb = time_label.strip().lower()  # "leave by" / "arrive ~"
    lines = [f"{cfg.emoji} *{cfg.name}* — {title}", ""]
    for name, dur, when, _miles, late, level, err in rows:
        if err:
            lines.append(f"{name} — _error_")
            continue
        mins = round(dur / 60)
        mark = f" {LEVEL_EMOJI[level]}" if level else ""
        flag = " ⚠️ leave now" if late else ""
        lines.append(f"{name} — *{mins} min*{mark}, {verb} {when:%-I:%M %p}{flag}")
    lines += ["", "_🟢 light · 🟠 moderate · 🔴 heavy traffic_", f"_{DISCLAIMER}_"]
    return "\n".join(lines)


def open_preview(text):
    """Write a WhatsApp-style preview to a temp HTML file and open it in the browser."""
    import html
    import tempfile
    import webbrowser

    rendered = html.escape(text)
    parts = rendered.split("*")
    rendered = "".join(p if i % 2 == 0 else f"<strong>{p}</strong>"
                       for i, p in enumerate(parts))
    rendered = rendered.replace("\n", "<br>")
    raw_js = json.dumps(text)

    page = f"""<!doctype html><html><head><meta charset="utf-8">
<title>ETA — WhatsApp preview</title><style>
body{{margin:0;font-family:-apple-system,Segoe UI,Helvetica,sans-serif;
background:#0b141a;display:flex;flex-direction:column;align-items:center;
min-height:100vh;padding:32px 16px;box-sizing:border-box}}
.phone{{width:100%;max-width:380px;background:#0b141a;
border-radius:16px;padding:18px 12px;box-shadow:0 8px 40px rgba(0,0,0,.5)}}
.bubble{{background:#005c4b;color:#e9edef;border-radius:10px;padding:10px 12px;
font-size:15px;line-height:1.45;max-width:85%;margin-left:auto;
box-shadow:0 1px 1px rgba(0,0,0,.3)}}
.bubble strong{{font-weight:700}}
.time{{font-size:11px;color:#8aa;text-align:right;margin-top:4px}}
button{{margin-top:22px;background:#00a884;color:#fff;border:0;border-radius:24px;
padding:12px 24px;font-size:15px;font-weight:600;cursor:pointer}}
button:active{{opacity:.8}} .ok{{color:#7fdba0;margin-top:10px;height:18px;font-size:13px}}
</style></head><body>
<div class="phone"><div class="bubble">{rendered}<div class="time">now ✓✓</div></div></div>
<button onclick="navigator.clipboard.writeText(MSG).then(()=>{{document.getElementById('ok').textContent='Copied — paste into WhatsApp'}})">Copy for WhatsApp</button>
<div class="ok" id="ok"></div>
<script>const MSG={raw_js};</script>
</body></html>"""

    f = tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8")
    f.write(page)
    f.close()
    webbrowser.open(f"file://{f.name}")
    return f.name


# --- Main ----------------------------------------------------------------

def main():
    api_key = os.environ.get("GMAPS_API_KEY")
    if not api_key:
        sys.exit("Set GMAPS_API_KEY (a Google Maps Platform key with Routes API enabled).")

    args = sys.argv[1:]
    whatsapp = any(a in ("-w", "--whatsapp") for a in args)
    preview = any(a in ("-p", "--preview") for a in args)

    config_path = DEFAULT_CONFIG
    arrive_override = None
    rest = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-c", "--config"):
            i += 1
            if i >= len(args):
                sys.exit("--config needs a path")
            config_path = args[i]
        elif a in ("-a", "--arrive"):
            i += 1
            if i >= len(args):
                sys.exit("--arrive needs a time, e.g. 19:00 or 7pm")
            arrive_override = args[i]
        elif a in ("-w", "--whatsapp", "-p", "--preview"):
            pass
        else:
            rest.append(a)
        i += 1
    arg = rest[0] if rest else None

    cfg = load_config(config_path)
    if arrive_override is not None:
        try:
            cfg.arrive_hour, cfg.arrive_min = parse_clock(arrive_override)
        except ValueError as e:
            sys.exit(str(e))
    dest_wp = waypoint(cfg.destination)
    now = dt.datetime.now(cfg.tz)
    now_mode = (arg or "").lower() == "now"

    if now_mode:
        title = f"live traffic right now ({now:%-I:%M %p %a})"
        time_label = "Arrive ~"
        depart_utc = now.astimezone(dt.timezone.utc) + dt.timedelta(seconds=30)
    else:
        arrival = resolve_arrival(arg, now, cfg)
        title = f"arrive by {arrival:%-I:%M %p}, {arrival:%a %b %-d}"
        time_label = "Leave by"

    rows = []
    for name, loc in cfg.origins.items():
        try:
            origin_wp = waypoint(loc)
            if now_mode:
                dur, meters = drive_duration(api_key, origin_wp, dest_wp, depart_utc)
                when = now + dt.timedelta(seconds=dur)
                late = False
            else:
                dur, when, meters, late = leave_by(api_key, origin_wp, dest_wp, arrival, now)
            try:
                level = traffic_level(dur, freeflow_seconds(api_key, origin_wp, dest_wp))
            except Exception:                            # noqa: BLE001 — marker is optional
                level = ""
            rows.append((name, dur, when, meters / 1609.344, late, level, None))
        except Exception as e:                           # noqa: BLE001 — show, don't crash
            rows.append((name, None, None, None, False, "", str(e)))

    rows.sort(key=lambda r: (r[1] is None, r[1] or 0))

    if preview:
        text = whatsapp_text(cfg, title, time_label, rows)
        path = open_preview(text)
        print(f"Opened WhatsApp preview in your browser ({path})\n")
        print(text)
    elif whatsapp:
        print(whatsapp_text(cfg, title, time_label, rows))
    else:
        print_table(cfg, title, time_label, rows)


if __name__ == "__main__":
    main()
