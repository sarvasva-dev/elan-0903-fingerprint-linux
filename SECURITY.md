# Security Policy

## Biometric Data Security & Privacy

`elan-0903-fingerprint-linux` is engineered with privacy and security as primary design requirements:

1. **Local-Only Processing**: Biometric matching and feature extraction occur entirely on the local CPU within a dedicated user-space process. No network connections are initiated, and no telemetry is gathered.
2. **Feature-Vector Storage**: Raw fingerprint images captured during enrollment are discarded immediately after feature extraction. Only Scale-Invariant Feature Transform (SIFT) keypoint coordinates and high-dimensional descriptor vectors are persisted in secure local templates (`/var/lib/elan_fingerprint/`). Raw ridge images cannot be reverse-engineered from descriptor vectors.
3. **Restricted Storage Permissions**: Template galleries are stored with restricted POSIX permissions (`0600` / `0700`) accessible only by root and the respective authenticated user.
4. **Privilege Isolation**: While PAM authentication hooks run with necessary privileges to unlock the desktop or authorize `sudo`, inter-process mutex locks (`fcntl.flock`) prevent race conditions and cross-session signal hijacking.

## Reporting a Vulnerability

If you discover a security vulnerability or privilege escalation bug in the PAM engine or driver:

1. Please do **not** open a public issue.
2. Send detailed disclosure and proof of concept to **ss8971132@gmail.com** or open a GitHub Private Security Advisory via the repository's Security tab.
3. We will respond promptly and publish a patch release.
