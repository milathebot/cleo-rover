from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Cleo Rover arrival-day calibration wizard scaffold')
    parser.add_argument('--output', default='config/rover.local.json')
    parser.add_argument('--non-interactive', action='store_true')
    args = parser.parse_args(argv)
    cfg = load_config().model_dump()
    checklist = [
        'confirm_pi_boot', 'confirm_wifi_ssh', 'test_body_api', 'test_display_static_png',
        'test_usb_mic_level', 'test_speaker_output', 'test_camera_snapshot',
        'test_left_motor_wheels_lifted', 'test_right_motor_wheels_lifted', 'set_motor_inversion',
        'set_max_duty_cycle', 'verify_stop_button_or_command',
    ]
    cfg['profile'] = 'hardware-calibration-pending'
    cfg['safety']['bench_safe_no_motors'] = True
    cfg['calibration'] = {'checklist': checklist, 'motors_may_arm_after_all_checks': False}
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cfg, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'ok': True, 'wrote': str(out), 'checks': checklist}, indent=2))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
