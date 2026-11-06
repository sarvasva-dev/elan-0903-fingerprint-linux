#!/usr/bin/env bash
set -e

# ==============================================================================
# Elan 04f3:0903 Linux Standalone Biometric Driver Installer (Arch / pearOS)
# Hardware Target: ASUS Vivobook 16 (04f3:0903)
# ==============================================================================

if [ "$EUID" -ne 0 ]; then
    echo "❌ Please run as root: sudo bash install-arch.sh"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="/opt/elan_fingerprint"
TARGET_STORAGE="/var/lib/elan_fingerprint"

echo "=== 1. Stopping & Disabling Buggy Upstream fprintd Service ==="
systemctl stop fprintd 2>/dev/null || true
systemctl mask fprintd 2>/dev/null || true

echo "=== 2. Installing udev Rule for USB Device 04f3:0903 ==="
cp -f "$SCRIPT_DIR/data/99-elan-fingerprint.rules" /etc/udev/rules.d/
udevadm control --reload-rules
udevadm trigger

echo "=== 3. Deploying Driver Source to $TARGET_DIR ==="
mkdir -p "$TARGET_DIR"
cp -f "$SCRIPT_DIR/src/"*.py "$TARGET_DIR/"
chmod 755 "$TARGET_DIR"/*.py

echo "=== 4. Setting Up Isolated Python Runtime in $TARGET_DIR ==="
python3 -m venv "$TARGET_DIR/.venv" --system-site-packages
"$TARGET_DIR/.venv/bin/pip" install --upgrade pip
"$TARGET_DIR/.venv/bin/pip" install numpy opencv-python-headless pyusb

echo "=== 5. Installing Global CLI Wrapper /usr/local/bin/elan-fingerprint ==="
cat << 'WRAPPER' > /usr/local/bin/elan-fingerprint
#!/usr/bin/env bash
if [ "$1" = "gui" ]; then
    exec /usr/bin/python3 "/opt/elan_fingerprint/elan_gui.py"
fi
exec "/opt/elan_fingerprint/.venv/bin/python" "/opt/elan_fingerprint/elan_auth.py" "$@"
WRAPPER
chmod 755 /usr/local/bin/elan-fingerprint

echo "=== 6. Initializing Biometric Storage ==="
mkdir -p "$TARGET_STORAGE"
chmod 777 "$TARGET_STORAGE"
touch "$TARGET_STORAGE/auth.log" "$TARGET_STORAGE/sensor.lock"
chmod 666 "$TARGET_STORAGE/auth.log" "$TARGET_STORAGE/sensor.lock"

echo "=== 7. Configuring Arch PAM for Passwordless Sudo ==="
if [ -f /etc/pam.d/sudo ]; then
    sed -i '/elan-fingerprint/d' /etc/pam.d/sudo
    # Insert sufficient check at top of auth stack
    sed -i '1i auth sufficient pam_exec.so quiet stdout /usr/local/bin/elan-fingerprint verify' /etc/pam.d/sudo
fi

echo "=== 8. Installing Desktop Application ==="
cp -f "$SCRIPT_DIR/data/elan-fingerprint.desktop" /usr/share/applications/ 2>/dev/null || true
update-desktop-database /usr/share/applications/ 2>/dev/null || true

echo "=========================================================="
echo "🎉 SUCCESS: Elan 04f3:0903 Standalone Driver Ready!"
echo "Enroll with: elan-fingerprint add 'Right Index'"
echo "=========================================================="
