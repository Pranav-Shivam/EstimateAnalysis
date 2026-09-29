from pathlib import Path

DEFAULT_CONFIDENCE_THRESHOLD = 0.8
KAPPA_ACCEPTABLE = 0.6
CALIBRATION_PATH = Path(__file__).resolve().parents[2] / "data" / "judge_calibration.json"
