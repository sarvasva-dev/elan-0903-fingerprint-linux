"""
ElanTech 04f3:0903 Standalone USB Fingerprint Driver
Reverse Engineered & Hardware Verified for ASUS Vivobook 16 (AMD Ryzen 5 5600H)
"""

import os
import time
import fcntl
import struct
import numpy as np
import usb.core
import usb.util
import cv2

VID = 0x04F3
PID = 0x0903
LOCK_FILE = "/var/lib/elan_fingerprint/sensor.lock"

# USB Endpoints (Hardware verified)
EP_CMD_OUT = 0x01  # Bulk OUT (commands)
EP_CMD_IN  = 0x83  # Bulk IN (command responses & finger touch events)
EP_IMG_IN  = 0x82  # Bulk IN (raw 16-bit capacitive image data)

# Hardware commands
CMD_GET_FW_VER = bytes([0x40, 0x19])
CMD_GET_DIM    = bytes([0x00, 0x0C])
CMD_GET_STATUS = bytes([0x40, 0x13])
CMD_PRE_SCAN   = bytes([0x40, 0x3F])
CMD_GET_IMAGE  = bytes([0x00, 0x09])
CMD_STOP       = bytes([0x00, 0x0B])


class ElanSensor:
    def __init__(self, width=80, height=80):
        self.width = width
        self.height = height
        self.raw_frame_size = self.width * self.height * 2  # 12,800 bytes
        self.dev = None
        self.background = None
        self.lock_fd = None

    def open(self):
        """Finds, acquires process lock, and claims the Elan USB fingerprint sensor"""
        # 1. Acquire inter-process lock to prevent GDM multi-worker collisions
        try:
            os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
            self.lock_fd = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR, 0o666)
            start_lock = time.time()
            acquired = False
            while time.time() - start_lock < 1.2:
                try:
                    fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except (BlockingIOError, IOError):
                    time.sleep(0.1)
            if not acquired:
                raise RuntimeError("Sensor is locked by another authentication process.")
        except RuntimeError:
            if self.lock_fd is not None:
                try:
                    os.close(self.lock_fd)
                except Exception:
                    pass
                self.lock_fd = None
            raise
        except Exception:
            if self.lock_fd is not None:
                try:
                    os.close(self.lock_fd)
                except Exception:
                    pass
                self.lock_fd = None

        # 2. Find USB device
        self.dev = usb.core.find(idVendor=VID, idProduct=PID)
        if self.dev is None:
            self.close()
            raise RuntimeError(f"Elan sensor {VID:04x}:{PID:04x} not found! Check USB connection or udev rules.")

        # Detach kernel driver if active
        for iface in range(1):
            try:
                if self.dev.is_kernel_driver_active(iface):
                    self.dev.detach_kernel_driver(iface)
            except Exception:
                pass

        # Check active configuration rather than resetting configuration
        try:
            _ = self.dev.get_active_configuration()
        except Exception:
            try:
                self.dev.set_configuration()
            except Exception:
                pass

        # Claim interface with retries
        claimed = False
        for _ in range(6):
            try:
                usb.util.claim_interface(self.dev, 0)
                claimed = True
                break
            except Exception:
                time.sleep(0.2)

        if not claimed:
            self.close()
            raise RuntimeError("Could not claim USB interface 0 (device busy).")

        self.flush()
        return self

    def close(self):
        """Safely stops sensor, releases USB interface, and releases process lock"""
        if self.dev is not None:
            try:
                self.send_cmd(CMD_STOP)
            except Exception:
                pass
            try:
                usb.util.release_interface(self.dev, 0)
            except Exception:
                pass
            self.dev = None

        if self.lock_fd is not None:
            try:
                fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                os.close(self.lock_fd)
            except Exception:
                pass
            self.lock_fd = None

    def flush(self):
        """Drains any leftover bytes from the endpoints"""
        if self.dev is None:
            return
        try:
            while True:
                self.dev.read(EP_CMD_IN, 64, timeout=10)
        except Exception:
            pass

    def send_cmd(self, cmd_bytes):
        self.dev.write(EP_CMD_OUT, cmd_bytes, timeout=1000)

    def read_resp(self, length, timeout=1000):
        return bytes(self.dev.read(EP_CMD_IN, length, timeout=timeout))

    def init_sensor(self):
        """Performs sensor handshake and reads sensor dimensions"""
        self.flush()

        # Read firmware version
        self.send_cmd(CMD_GET_FW_VER)
        fw = self.read_resp(2)

        # Read dimensions
        self.send_cmd(CMD_GET_DIM)
        dim = self.read_resp(4)
        if dim and len(dim) >= 4:
            self.width = dim[0] + 1
            self.height = dim[2] + 1
            self.raw_frame_size = self.width * self.height * 2

        # Capture baseline background frame
        self.capture_background()

    def capture_background(self):
        """Captures an empty background frame for fixed pattern noise cancellation"""
        try:
            self.send_cmd(CMD_GET_IMAGE)
            raw = bytes(self.dev.read(EP_IMG_IN, self.raw_frame_size, timeout=1500))
            self.send_cmd(CMD_STOP)
            arr = np.frombuffer(raw, dtype=np.uint16).reshape((self.height, self.width))
            self.background = arr.astype(np.float32)
        except Exception:
            try:
                self.send_cmd(CMD_STOP)
            except Exception:
                pass
            self.background = None

    def wait_for_finger(self, timeout_sec=10):
        """
        Arms the sensor with CMD_PRE_SCAN and polls for finger contact (0x55).
        Returns True when finger is placed, False on timeout.
        """
        self.flush()
        self.send_cmd(CMD_PRE_SCAN)

        start = time.time()
        while time.time() - start < timeout_sec:
            try:
                resp = self.read_resp(1, timeout=400)
                if resp and resp[0] == 0x55:
                    return True
            except (usb.core.USBTimeoutError, usb.core.USBError) as e:
                if "timed out" in str(e).lower() or getattr(e, "errno", None) == 110:
                    continue
                time.sleep(0.05)
            except Exception:
                time.sleep(0.05)

        # Timeout reached
        try:
            self.send_cmd(CMD_STOP)
        except Exception:
            pass
        return False

    def process_raw_frame(self, raw_data):
        """Converts raw 16-bit uint16 USB buffer to enhanced 160x160 fingerprint image"""
        if len(raw_data) < self.raw_frame_size:
            raise IOError(f"Truncated frame: expected {self.raw_frame_size}, got {len(raw_data)}")

        frame16 = np.frombuffer(raw_data, dtype=np.uint16).reshape((self.height, self.width)).copy()

        # FPN suppression using background subtraction if available
        if self.background is not None:
            diff = frame16.astype(np.float32) - self.background
            p1, p99 = np.percentile(diff, (2, 98))
            if p99 > p1 + 15:
                norm8 = np.clip((diff - p1) / (p99 - p1) * 255.0, 0, 255).astype(np.uint8)
            else:
                p1, p99 = np.percentile(frame16, (2, 98))
                norm8 = np.clip((frame16.astype(np.float32) - p1) / (p99 - p1 + 1e-5) * 255.0, 0, 255).astype(np.uint8)
        else:
            p1, p99 = np.percentile(frame16, (2, 98))
            norm8 = np.clip((frame16.astype(np.float32) - p1) / (p99 - p1 + 1e-5) * 255.0, 0, 255).astype(np.uint8)

        # Enhance ridge patterns using CLAHE
        clahe = cv2.createCLAHE(clipLimit=3.5, tileGridSize=(8, 8))
        enhanced = clahe.apply(norm8)

        # Upscale 2x using bicubic interpolation for rich keypoint detection (160x160)
        enhanced_upscaled = cv2.resize(enhanced, (self.width * 2, self.height * 2), interpolation=cv2.INTER_CUBIC)
        return enhanced_upscaled

    def capture_single_frame(self):
        """Captures raw image from bulk EP_IMG_IN immediately following finger detection"""
        time.sleep(0.02)  # Stabilization pause
        self.send_cmd(CMD_GET_IMAGE)
        raw_data = bytes(self.dev.read(EP_IMG_IN, self.raw_frame_size, timeout=2000))
        self.send_cmd(CMD_STOP)
        return self.process_raw_frame(raw_data)

    def wait_and_capture(self, timeout_sec=10):
        """Convenience function: arms sensor, waits for touch, and returns enhanced image"""
        if self.wait_for_finger(timeout_sec=timeout_sec):
            return self.capture_single_frame()
        return None
