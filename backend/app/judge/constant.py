from pathlib import Path

DEFAULT_CONFIDENCE_THRESHOLD = 0.8
KAPPA_ACCEPTABLE = 0.6
FALSE_AUTO_SEND_CEILING = 0.05
CALIBRATION_PATH = Path(__file__).resolve().parents[2] / "data" / "judge_calibration.json"
