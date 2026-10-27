#!/usr/bin/env bash
set -e

# ==============================================================================
# Elan 04f3:0903 Linux Standalone Biometric Driver Uninstaller
# ==============================================================================

if [ "$EUID" -ne 0 ]; then
    echo "❌ Please run as root: sudo bash uninstall.sh"
    exit 1
fi

echo "=== 1. Removing PAM Integration ==="
sed -i '/elan-fingerprint/d' /etc/pam.d/common-auth 2>/dev/null || true
rm -f /usr/share/pam-configs/elan-fingerprint 2>/dev/null || true

echo "=== 2. Removing udev Rules ==="
rm -f /etc/udev/rules.d/99-elan-fingerprint.rules
udevadm control --reload-rules
udevadm trigger

echo "=== 3. Removing Installed Binaries & Desktop App ==="
rm -f /usr/local/bin/elan-fingerprint
rm -f /usr/share/applications/elan-fingerprint.desktop
rm -rf /opt/elan_fingerprint

echo "=== 4. Unmasking Standard fprintd (Optional) ==="
systemctl unmask fprintd 2>/dev/null || true

echo "=========================================================="
echo "✅ SUCCESS: Elan driver removed and system PAM restored."
echo "Note: Your enrolled biometric keys in /var/lib/elan_fingerprint"
echo "were preserved. To remove them manually, run: sudo rm -rf /var/lib/elan_fingerprint"
echo "=========================================================="
