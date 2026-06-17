# masjid-eta

A tiny CLI that tells you predicted driving times from several starting points to
one destination, sized for a target arrival time — and tells you when to leave.
Built for "what time should I leave to make the 9:45 jamaat?" but the destination,
arrival time, and origins are all configurable, so point it anywhere.

It uses the **Google Routes API** with predicted, traffic-aware routing, so the
numbers reflect expected congestion for that specific morning, not free-flow times.

```
🕌 Masjid ETA — arrive by 9:45 AM, Sat Jun 20

East McKinney — *6 min* 🟢, leave by 9:38 AM
Allen — *11 min* 🟢, leave by 9:33 AM
West McKinney — *18 min* 🟡, leave by 9:27 AM
...
```

## Setup

1. **Install the one dependency:**
   ```bash
   pip install requests
   ```

2. **Get a Google Maps Platform API key** with the **Routes API** enabled
   (Google Cloud Console → APIs & Services). Restrict the key to the Routes API.
   The free monthly credit comfortably covers personal use.

3. **Provide the key** via an environment variable:
   ```bash
   export GMAPS_API_KEY=your_key_here
   ```

4. **Configure your destination and origins:**
   ```bash
   cp config.example.json config.json   # then edit config.json
   ```

## Configuration (`config.json`)

Everything is data — no code edits needed.

| Field | Meaning |
|-------|---------|
| `name`, `emoji` | Label shown in the output header |
| `destination` | An address string **or** `{ "lat": .., "lng": .. }` |
| `arrive` | Target arrival time, 24-hour `"HH:MM"` |
| `timezone` | IANA name, e.g. `"America/Chicago"` |
| `origins` | Map of label → address string **or** `{ "lat": .., "lng": .. }` |

Each origin (and the destination) can be a plain address or precise coordinates:

```json
{
  "destination": "1410 S Tennessee St, McKinney, TX 75069",
  "arrive": "09:45",
  "timezone": "America/Chicago",
  "origins": {
    "My house": "123 Example Dr, Your City, ST 00000",
    "Frisco":   { "lat": 33.1518, "lng": -96.8278 }
  }
}
```

## Usage

```bash
python masjid_eta.py            # next occurrence of today's weekday
python masjid_eta.py sat        # next Saturday
python masjid_eta.py 2026-06-20 # a specific date
python masjid_eta.py now        # live traffic right now (shows projected arrival)
```

Flags (combine freely):

| Flag | Effect |
|------|--------|
| `-w`, `--whatsapp` | Print WhatsApp-ready text (copy-paste into a chat) |
| `-p`, `--preview` | Open a formatted WhatsApp-style preview in your browser, with a Copy button |
| `-c`, `--config P` | Use a different config file |
| `-a`, `--arrive T` | Override the arrival time for this run, e.g. `19:00`, `7pm`, `9:45am` |
| `--send` | (macOS) Send the WhatsApp-formatted report to a group via WhatsApp Desktop |
| `--stage` | (macOS) Dry run — open the group and paste, but do **not** press send |
| `--group "Name"` | Target group (overrides `whatsapp_group` in config) |
| `--map` | Render a static PNG map — route lines + colored origin markers + labels |
| `--map-out P` | Map output path (default `~/masjid-map.png`) |

## Map visualization

```bash
python masjid_eta.py sat --map
```

Renders a static PNG showing each driving route as a line colored by traffic
(🟢 light / 🟠 moderate / 🔴 heavy), a colored dot + `name + drive time` label per
origin, and the destination marked in the middle. The map is drawn from
OpenStreetMap tiles with Pillow — **no mapping API key needed** (route geometry
comes from the Routes API you already use). Requires `Pillow` (`pip install Pillow`).
On macOS the image opens automatically; the file is shareable (e.g. drop into chat).

## Sending to a WhatsApp group (macOS only)

The tool can deliver the report straight to a WhatsApp group by automating the
**WhatsApp Desktop** app. Add the group name to your config:

```json
"whatsapp_group": "Masjid Carpool"
```

Then:

```bash
python masjid_eta.py sat --stage   # safe first: opens the group + pastes, no send
python masjid_eta.py sat --send    # actually sends
```

How it works: the report (WhatsApp-formatted) is copied to your clipboard, then an
AppleScript (`send_whatsapp.applescript`) activates WhatsApp, opens a new-chat
search, types the group name, opens the top match, pastes, and presses send.

**Requirements & caveats:**
- macOS with the WhatsApp Desktop app installed and signed in.
- Grant **Accessibility** permission to whatever runs it: System Settings →
  Privacy & Security → Accessibility (enable your terminal app). Without it,
  macOS blocks the keystrokes.
- It targets the **top search result** for the group name, so use a name unique
  enough to match the right chat. Run `--stage` first to confirm.
- This automates your own desktop app; it does not use any WhatsApp API.

A convenience wrapper is included:

```bash
./eta sat -w
```

## How it works

- **Arrival vs. departure.** Google's driving routes take a *departure* time, not an
  arrival time. To answer "leave by X to arrive at 9:45," the tool runs a short
  fixed-point iteration on the departure time until it converges (usually 2–3 calls).
- **Traffic marker.** For each origin it also requests a traffic-free baseline and
  compares: 🟢 light, 🟠 moderate (~5+ min slower), 🔴 heavy (~10+ min slower).
- **`now` mode** departs immediately using live traffic and reports your projected
  arrival instead of a leave-by time.

## Disclaimer

Point-in-time estimate from Google Maps APIs. Actual traffic and travel times will
vary — no guarantees. You are responsible for your own Google Maps Platform usage
and any associated costs.

## License

MIT — see [LICENSE](LICENSE).
