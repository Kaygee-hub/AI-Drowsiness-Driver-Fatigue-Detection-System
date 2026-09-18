# Real-Time AI Driver Fatigue & Drowsiness Detection System

An edge-ready driver monitoring system built with OpenCV, MediaPipe Tasks Vision, and Tkinter. The application analyzes real-time facial landmarker telemetry to detect fatigue indicators (drowsiness, yawning, and microsleep head drops), triggering local audio alerts, CSV logging, and remote MQTT telemetry broadcasts.

---

## Key Features

* **Multi-Metric Fatigue Analysis:**
  * **Eye Aspect Ratio (EAR):** Detects prolonged eye closures and microsleep.
  * **Mouth Aspect Ratio (MAR):** Tracks yawning frequency and duration.
  * **Head Displacement Ratio:** Measures sudden vertical posture drops relative to baseline calibration.
* **Non-Blocking Multithreaded Audio:** Uses background daemon threads for audio alerts to prevent UI frame freezing.
* **IoT Telemetry Broadcasting:** Publishes structured JSON alert payloads over MQTT (`paho-mqtt`) to a central broker (`broker.hivemq.com`).
* **Automated Logging:** Saves local timestamped event logs to `fatigue_event_log.csv`.
* **GUI Dashboard:** Interactive desktop UI with live camera view, dynamic risk bar, metric counters, and calibration controls.

---

## Tech Stack

* **Language:** Python 3.9+
* **Computer Vision:** OpenCV, MediaPipe Tasks Vision (`FaceLandmarker`)
* **GUI Framework:** Tkinter, Pillow
* **IoT Protocol:** MQTT (`paho-mqtt`)
* **Data Processing:** NumPy

---

## Quick Start

### 1. Clone the Repository
```bash
git clone [https://github.com/YOUR_USERNAME/ai-driver-fatigue-detection.git](https://github.com/YOUR_USERNAME/ai-driver-fatigue-detection.git)
cd ai-driver-fatigue-detection
