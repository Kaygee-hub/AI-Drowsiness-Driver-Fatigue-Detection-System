# 4IR Mining Fleet | Driver Fatigue Telemetry

A real-time driver fatigue monitoring system built for mining fleet vehicles.
It watches the driver's eyes, mouth, and head position through a webcam,
scores fatigue risk continuously, alerts the driver, and streams telemetry
over MQTT for a fleet control room to consume.

Built as a Fourth Industrial Revolution (4IR) style safety tool: computer
vision + AI at the edge, real-time alerting, and IoT telemetry, aimed at
reducing fatigue-related incidents on mine sites — where fatigue driving is
one of the leading causes of haul truck accidents.

## Features

- **Driver identification** — name, permit ID, and vehicle ID captured at
  session start
- **Multi-cue fatigue detection**
  - Eye Aspect Ratio (EAR) — detects closed / drooping eyes
  - Mouth Aspect Ratio (MAR) — detects yawning
  - Head-drop detection — detects nodding off, calibrated per driver at
    session start
- **Decaying fatigue score (0–100)** instead of a hard "3 strikes" rule —
  climbs while fatigue cues are active, decays while the driver is alert,
  and moves through NORMAL → CAUTION → HIGH → CRITICAL bands
- **Live dashboard** — Tkinter UI showing the camera feed, live metric
  cards, current status, and a scrolling event log
- **Loud, sustained audible alarm** on CRITICAL status — keeps ringing
  until the driver's state improves, rather than a single easy-to-miss beep
- **MQTT telemetry** — publishes session start/end, per-second telemetry,
  and fatigue alerts to a broker (`mining/fleet/<truck_id>/...` topics),
  ready to feed a fleet control room dashboard
- **Local event logging** — every fatigue event is written to
  `fatigue_event_log.csv` for review and reporting
- **Company branding** — drop a `logo.png` next to the script and it
  appears in the dashboard automatically

## Tech stack

- Python 3
- [OpenCV](https://opencv.org/) — camera capture and drawing
- [MediaPipe Face Landmarker](https://developers.google.com/mediapipe) —
  facial landmark detection
- Tkinter + Pillow — desktop dashboard UI
- [paho-mqtt](https://pypi.org/project/paho-mqtt/) — telemetry publishing

## Getting started

### 1. Install dependencies

```bash
pip install opencv-python mediapipe pillow paho-mqtt
```

(This also runs fine from [Thonny](https://thonny.org/) — just install the
same packages via Tools → Manage Packages.)

### 2. Run it

```bash
python main.py
```

On first run, the app automatically downloads the MediaPipe
`face_landmarker.task` model file into the project folder.

### 3. (Optional) Add your logo

Drop a `logo.png`, `logo.jpg`, or `logo.jpeg` file into the project folder
and it will show up in the dashboard's sidebar automatically.

### 4. (Optional) Point it at your MQTT broker

Edit the config block at the top of `main.py`:

```python
MQTT_BROKER = "broker.hivemq.com"  # replace with your private broker / AWS IoT endpoint
MQTT_PORT = 1883
```

## How the fatigue score works

Each frame, three cues are evaluated:

| Cue        | Signal                                   | Trigger                          |
|------------|-------------------------------------------|-----------------------------------|
| Eyes       | Eye Aspect Ratio (EAR)                    | Sustained closure below threshold |
| Mouth      | Mouth Aspect Ratio (MAR)                  | Sustained opening (yawning)       |
| Head       | Nose position vs. calibrated baseline     | Sustained downward drop           |

When any cue is active, the fatigue score increases; when the driver looks
normal, it decays. The score maps to a status band:

- **0–29** → NORMAL
- **30–59** → CAUTION
- **60–84** → HIGH
- **85–100** → CRITICAL (triggers a loud, sustained alarm and an MQTT alert)

## MQTT topics

| Topic                                | Payload                                              |
|---------------------------------------|-------------------------------------------------------|
| `mining/fleet/<truck_id>/session`     | Session start / end events                            |
| `mining/fleet/<truck_id>/telemetry`   | EAR, MAR, head status, fatigue score, status (1/sec)   |
| `mining/fleet/<truck_id>/alerts`      | HIGH / CRITICAL fatigue escalation alerts              |

## Roadmap ideas

- Multi-sensor fusion with vehicle CAN-bus data (speed, steering) to cut
  false positives
- Fleet-wide control room dashboard consuming the MQTT stream
- Shift-pattern analytics (fatigue trends by driver, by roster)
- Mine-spec hardware packaging (ruggedized enclosure, IR camera for
  low-light cabs)

## Disclaimer

This is a prototype / learning project, not a certified safety device. It
has not been validated against real mine-site conditions or safety
standards, and should not be relied on as a sole safeguard against
fatigue-related incidents.

## Author

Built by **[Kgaogelo Lekhuleni]**.

This project is part of my personal portfolio work in 4IR / mining
technology and computer vision. I'm open to conversations about
collaboration, licensing, or opportunities related to this work —
reach out via [kgaogeloexcellent10111@gmail.com / www.linkedin.com/in/kgaogelo-lekhuleni-28430b366].

## License

All Rights Reserved — see [LICENSE](LICENSE). This code is shared publicly
for demonstration purposes; it is not open source and may not be copied,
modified, or reused without written permission. See the license file for
how to request permission.
