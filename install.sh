#!/usr/bin/env bash
set -e

# ==============================================================================
# Elan 04f3:0903 Linux Standalone Biometric Driver Installer
# Hardware Target: ASUS Vivobook 16 (M1603QA / AMD Ryzen 5000 Series)
# ==============================================================================

if [ "$EUID" -ne 0 ]; then
    echo "❌ Please run as root: sudo bash install.sh"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="/opt/elan_fingerprint"
TARGET_STORAGE="/var/lib/elan_fingerprint"

echo "=== 1. Stopping & Disabling Buggy fprintd Service ==="
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
# Check if python3-venv or uv is available
if command -v uv &> /dev/null; then
    export UV_LINK_MODE=copy
    uv venv "$TARGET_DIR/.venv" --python /usr/bin/python3
    uv pip install --python "$TARGET_DIR/.venv" numpy opencv-python-headless pyusb
else
    python3 -m venv "$TARGET_DIR/.venv" --system-site-packages
    "$TARGET_DIR/.venv/bin/pip" install --upgrade pip
    "$TARGET_DIR/.venv/bin/pip" install numpy opencv-python-headless pyusb
fi

echo "=== 5. Installing Global CLI Wrapper /usr/local/bin/elan-fingerprint ==="
cat << 'EOF' > /usr/local/bin/elan-fingerprint
#!/usr/bin/env bash
if [ "$1" = "gui" ]; then
    exec /usr/bin/python3 "/opt/elan_fingerprint/elan_gui.py"
fi
exec "/opt/elan_fingerprint/.venv/bin/python" "/opt/elan_fingerprint/elan_auth.py" "$@"
EOF
chmod 755 /usr/local/bin/elan-fingerprint

echo "=== 6. Configuring Linux PAM for Passwordless Sudo & Lock Screen ==="
# Remove old/buggy fprintd pam hooks
pam-auth-update --package --remove fprintd 2>/dev/null || true
sed -i '/pam_fprintd/d' /etc/pam.d/common-auth 2>/dev/null || true
sed -i '/elan-fingerprint/d' /etc/pam.d/common-auth 2>/dev/null || true
rm -f /usr/share/pam-configs/elan-fingerprint 2>/dev/null || true

# Insert clean sufficient rule right before pam_unix.so
sed -i '/pam_unix.so/i auth\tsufficient\tpam_exec.so quiet stdout /usr/local/bin/elan-fingerprint verify' /etc/pam.d/common-auth

echo "=== 7. Initializing Secure Biometric Storage ==="
mkdir -p "$TARGET_STORAGE"
chmod 777 "$TARGET_STORAGE"
touch "$TARGET_STORAGE/auth.log" "$TARGET_STORAGE/sensor.lock"
chmod 666 "$TARGET_STORAGE/auth.log" "$TARGET_STORAGE/sensor.lock"

echo "=== 8. Installing Desktop Application ==="
cp -f "$SCRIPT_DIR/data/elan-fingerprint.desktop" /usr/share/applications/
update-desktop-database /usr/share/applications/ 2>/dev/null || true

echo "=========================================================="
echo "🎉 SUCCESS: Elan 04f3:0903 Standalone Driver Installed!"
echo ""
echo "Next Steps:"
echo "  1. Enroll your first fingerprint:"
echo "     elan-fingerprint add 'Right Index'"
echo ""
echo "  2. Test passwordless sudo:"
echo "     sudo -k && sudo whoami"
echo ""
echo "  3. Launch Graphical Settings:"
echo "     elan-fingerprint gui"
echo "=========================================================="
