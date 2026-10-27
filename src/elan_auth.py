#!/usr/bin/env python3
"""
Elan Fingerprint Authentication Manager & PAM Helper
Reverse Engineered & Hardware Verified for ASUS Vivobook 16 (04f3:0903)
"""

import sys
import os
import time
import pickle
import getpass
import logging
import numpy as np
import cv2

# Set up logging for PAM and verification tracking (safe failover)
LOG_PATH = "/var/lib/elan_fingerprint/auth.log"
try:
    logging.basicConfig(
        filename=LOG_PATH,
        level=logging.INFO,
        format="%(asctime)s [%(process)d] %(levelname)s: %(message)s"
    )
except Exception:
    logging.basicConfig(level=logging.CRITICAL)

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from elan_sensor import ElanSensor
from biometric_matcher import BiometricMatcher

SYSTEM_TEMPLATES_DIR = "/var/lib/elan_fingerprint"


def get_target_username(provided_username=None):
    """Accurately determines target username across PAM, sudo, and normal shell"""
    if provided_username:
        return provided_username
    pam_user = os.environ.get("PAM_USER")
    if pam_user:
        return pam_user
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        return sudo_user
    current = getpass.getuser()
    if current != "root":
        return current
    # If running as root, detect primary user in /home
    try:
        home_users = [u for u in os.listdir("/home") if os.path.isdir(os.path.join("/home", u))]
        if "sarthak" in home_users:
            return "sarthak"
        if len(home_users) > 0:
            return home_users[0]
    except Exception:
        pass
    return "root"


def get_template_paths(username):
    """Returns list of paths where user's biometric template can be stored or found"""
    user_home = os.path.expanduser(f"~{username}")
    if not os.path.isdir(user_home):
        user_home = f"/home/{username}"
    user_file = os.path.join(user_home, ".config/elan_fingerprint/templates.pkl")
    sys_file = os.path.join(SYSTEM_TEMPLATES_DIR, f"{username}.pkl")
    return user_file, sys_file


def save_templates(username, templates_data):
    """Saves biometric templates to both user ~/.config and /var/lib/elan_fingerprint"""
    user_file, sys_file = get_template_paths(username)
    saved_any = False

    # 1. Save to user ~/.config
    try:
        user_dir = os.path.dirname(user_file)
        os.makedirs(user_dir, exist_ok=True)
        with open(user_file, "wb") as f:
            pickle.dump(templates_data, f)
        os.chmod(user_file, 0o600)
        saved_any = True
    except Exception as e:
        print(f"Warning: Could not save to {user_file}: {e}")

    # 2. Save to /var/lib/elan_fingerprint
    try:
        os.makedirs(SYSTEM_TEMPLATES_DIR, exist_ok=True)
        with open(sys_file, "wb") as f:
            pickle.dump(templates_data, f)
        os.chmod(sys_file, 0o644)
        saved_any = True
    except Exception:
        pass

    return saved_any


def load_templates(username):
    """Loads templates from system store or user config"""
    user_file, sys_file = get_template_paths(username)
    for path in [sys_file, user_file]:
        try:
            if os.path.exists(path):
                with open(path, "rb") as f:
                    return pickle.load(f), path
        except Exception:
            continue
    return None, None


def load_templates_dict(username):
    """Loads templates dictionary {finger_name: samples} with backward compatibility"""
    raw, path = load_templates(username)
    if raw is None:
        return {}, path
    if isinstance(raw, list):
        return {"Finger 1 (Main)": raw}, path
    elif isinstance(raw, dict):
        return raw, path
    return {}, path


def cmd_test():
    print("=== Elan 04f3:0903 Hardware Diagnostic Test ===")
    sensor = ElanSensor()
    matcher = BiometricMatcher()
    try:
        sensor.open()
        print("✅ Successfully opened USB device 04f3:0903!")
        sensor.init_sensor()
        print(f"✅ Sensor Initialized: Dimensions {sensor.width}x{sensor.height}")
        print("\n👉 Touch the fingerprint sensor now to test capture (waiting up to 10s)...")

        img = sensor.wait_and_capture(timeout_sec=10)
        if img is not None:
            print("✅ Finger contact detected and frame captured successfully!")
            user = get_target_username()
            user_home = os.path.expanduser(f"~{user}")
            debug_dir = os.path.join(user_home, ".config/elan_fingerprint")
            os.makedirs(debug_dir, exist_ok=True)
            debug_img_path = os.path.join(debug_dir, "last_scan.png")
            cv2.imwrite(debug_img_path, img)

            pts, desc = matcher.extract_features(img)
            kp_count = len(pts)
            print(f"✅ Extracted {kp_count} biometric keypoints from 160x160 enhanced image!")
            print(f"✅ Frame saved to: {debug_img_path}")
            print("\n🎉 Hardware and image pipeline are working perfectly!")
            return 0
        else:
            print("⚠️ Timeout: No finger touch was detected within 10 seconds.")
            return 1
    except Exception as e:
        print(f"❌ Error during test: {e}")
        return 1
    finally:
        sensor.close()


def cmd_enroll(username=None, finger_name=None):
    target_user = get_target_username(username)
    gallery_dict, _ = load_templates_dict(target_user)

    if not finger_name:
        default_idx = len(gallery_dict) + 1
        finger_name = f"Finger {default_idx}"

    print(f"\n=======================================================")
    print(f"  Enrolling '{finger_name}' for user: {target_user}")
    print(f"=======================================================")
    print("Please follow the prompts to enroll your finger (4 samples).")

    sensor = ElanSensor()
    matcher = BiometricMatcher()

    try:
        sensor.open()
        sensor.init_sensor()
    except Exception as e:
        print(f"❌ Failed to initialize sensor: {e}")
        return 1

    NUM_SAMPLES = 4
    enrolled_templates = []
    step = 1

    try:
        while step <= NUM_SAMPLES:
            if step == 1:
                prompt_hint = "Place your finger straight in the center"
            elif step == 2:
                prompt_hint = "Place your finger slightly higher/forward"
            elif step == 3:
                prompt_hint = "Place your finger slightly to the left"
            else:
                prompt_hint = "Place your finger firmly in the center"

            print(f"\n👉 [Sample {step}/{NUM_SAMPLES}]: {prompt_hint}...")
            img = sensor.wait_and_capture(timeout_sec=12)

            if img is None:
                print("⏱️ Touch timeout. Please touch the sensor firmly.")
                continue

            pts, desc = matcher.extract_features(img)
            if desc is None or len(pts) < 15:
                print("⚠️ Low ridge contrast or partial touch. Please lift and try again...")
                time.sleep(1.2)
                continue

            enrolled_templates.append((pts, desc))
            print(f"  ✅ Sample {step} captured successfully ({len(pts)} keypoints extracted)!")
            print("  (Lift your finger...)")
            step += 1
            time.sleep(1.2)

        gallery_dict[finger_name] = enrolled_templates
        if save_templates(target_user, gallery_dict):
            user_path, _ = get_template_paths(target_user)
            print("\n=======================================================")
            print(f"🎉 SUCCESS: '{finger_name}' enrolled successfully!")
            print(f"Total enrolled fingers for {target_user}: {len(gallery_dict)}")
            for idx, f in enumerate(gallery_dict.keys(), 1):
                print(f"  {idx}. {f}")
            print("=======================================================\n")
            return 0
        else:
            print("❌ Failed to save biometric template to disk.")
            return 1

    except Exception as e:
        print(f"❌ Error during enrollment: {e}")
        return 1
    finally:
        sensor.close()


def cmd_list(username=None):
    target_user = get_target_username(username)
    gallery_dict, _ = load_templates_dict(target_user)
    if not gallery_dict:
        print(f"\nℹ️ No enrolled fingerprints found for '{target_user}'.\n")
        return 0

    print(f"\n=======================================================")
    print(f"  Enrolled Fingerprints for user: {target_user}")
    print(f"=======================================================")
    for idx, (f_name, f_samples) in enumerate(gallery_dict.items(), 1):
        print(f"  [{idx}] {f_name} ({len(f_samples)} biometric samples)")
    print("=======================================================\n")
    return 0


def cmd_remove(username=None, finger_name=None):
    target_user = get_target_username(username)
    gallery_dict, _ = load_templates_dict(target_user)

    if not gallery_dict:
        print(f"❌ No enrolled fingerprints found for user '{target_user}'.")
        return 1

    if not finger_name:
        print("Usage: elan-fingerprint remove <finger_name_or_number>")
        cmd_list(target_user)
        return 1

    matched_key = None
    if finger_name in gallery_dict:
        matched_key = finger_name
    elif finger_name.isdigit():
        idx = int(finger_name)
        keys = list(gallery_dict.keys())
        if 1 <= idx <= len(keys):
            matched_key = keys[idx - 1]

    if matched_key:
        del gallery_dict[matched_key]
        save_templates(target_user, gallery_dict)
        print(f"\n✅ SUCCESS: Removed '{matched_key}' from {target_user}'s enrolled fingers.")
        cmd_list(target_user)
        return 0
    else:
        print(f"❌ Finger '{finger_name}' not found.")
        cmd_list(target_user)
        return 1


def cmd_clear(username=None):
    target_user = get_target_username(username)
    save_templates(target_user, {})
    print(f"\n✅ All enrolled fingerprints removed for user '{target_user}'.\n")
    return 0


def cmd_verify(username=None):
    target_user = get_target_username(username)
    pam_service = os.environ.get("PAM_SERVICE", "terminal/cli")
    logging.info(f"Verification request started: user='{target_user}', service='{pam_service}'")

    gallery_dict, tpath = load_templates_dict(target_user)

    if not gallery_dict:
        logging.warning(f"No enrolled template found for '{target_user}'.")
        print(f"❌ No enrolled fingerprint found for user '{target_user}'.", flush=True)
        return 1

    # Flatten all fingers' samples for unified matching
    all_gallery = []
    finger_index = []
    for f_name, f_samples in gallery_dict.items():
        for sample in f_samples:
            all_gallery.append(sample)
            finger_index.append(f_name)

    sensor = ElanSensor()
    matcher = BiometricMatcher(inlier_threshold=6)

    try:
        sensor.open()
        sensor.init_sensor()
        logging.info("Sensor initialized, waiting for finger (timeout 8s)...")
        print(f"[Fingerprint] Touch sensor to authenticate ({target_user})...", flush=True)

        img = sensor.wait_and_capture(timeout_sec=8)
        if img is None:
            logging.info("Timed out waiting for finger touch.")
            print("[Fingerprint] Timed out.", flush=True)
            return 1

        logging.info("Finger detected, verifying biometric features across all enrolled fingers...")
        matched, score = matcher.verify(all_gallery, img)
        if matched:
            logging.info(f"Biometric match SUCCESS! Score={score}")
            print(f"✅ Fingerprint match confirmed! (Score: {score})", flush=True)
            return 0
        else:
            logging.warning(f"Biometric match FAILED. Score={score}/6")
            print(f"❌ Fingerprint did not match (Score: {score}/6)", flush=True)
            return 1

    except RuntimeError as re:
        logging.warning(f"Sensor runtime issue (possibly concurrent worker): {re}")
        return 1
    except Exception as e:
        logging.error(f"Authentication exception: {e}")
        return 1
    finally:
        sensor.close()


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "help"
    arg2 = sys.argv[2] if len(sys.argv) > 2 else None
    arg3 = sys.argv[3] if len(sys.argv) > 3 else None

    if action == "test":
        sys.exit(cmd_test())
    elif action in ("enroll", "add"):
        # Support: elan-fingerprint add "Right Thumb"
        # Support: elan-fingerprint enroll sarthak
        if arg2 and not arg2.startswith("-"):
            if arg2 in os.listdir("/home"):
                sys.exit(cmd_enroll(username=arg2, finger_name=arg3))
            else:
                sys.exit(cmd_enroll(username=arg3, finger_name=arg2))
        else:
            sys.exit(cmd_enroll())
    elif action in ("list", "ls"):
        sys.exit(cmd_list(arg2))
    elif action in ("remove", "delete", "rm"):
        sys.exit(cmd_remove(finger_name=arg2, username=arg3))
    elif action == "clear":
        sys.exit(cmd_clear(arg2))
    elif action == "verify":
        try:
            sys.exit(cmd_verify(arg2))
        except Exception:
            sys.exit(1)
    else:
        print("Elan 04f3:0903 Fingerprint Management Tool")
        print("\nUsage:")
        print("  elan-fingerprint add [finger_name]     - Add / enroll another finger (e.g. 'Right Thumb')")
        print("  elan-fingerprint list                  - List all registered fingerprints")
        print("  elan-fingerprint remove <name_or_num>  - Remove a specific fingerprint")
        print("  elan-fingerprint clear                 - Remove all registered fingerprints")
        print("  elan-fingerprint test                  - Test sensor connection & capture")
        print("  elan-fingerprint verify                - Verify fingerprint match")
        sys.exit(0)


if __name__ == "__main__":
    main()
