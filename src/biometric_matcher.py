"""
Biometric Matching Engine for Elan Fingerprint Sensor (04f3:0903)
Uses Scale-Invariant Feature Transform (SIFT) with Difference-of-Gaussians (DoG)
scale-space and RANSAC geometric affine consistency (matching Windows WinBio FingerSA engine).
"""

import numpy as np
import cv2


class BiometricMatcher:
    def __init__(self, inlier_threshold=6):
        # SIFT detector tuned for capacitive fingerprint ridge structures
        self.sift = cv2.SIFT_create(
            nfeatures=600,
            nOctaveLayers=3,
            contrastThreshold=0.02,  # Sensitive to subtle ridge contrasts
            edgeThreshold=15,        # Higher threshold retains ridge endings & bifurcations
            sigma=1.6
        )
        self.inlier_threshold = inlier_threshold

    def extract_features(self, img):
        """
        Extracts keypoint coordinates and SIFT descriptors from a fingerprint image.
        Returns: (pts, descriptors) where pts is (N, 2) float32 array of (x, y) coordinates.
        """
        if img is None:
            return np.empty((0, 2), dtype=np.float32), None

        keypoints, descriptors = self.sift.detectAndCompute(img, None)
        if descriptors is None or len(keypoints) == 0:
            return np.empty((0, 2), dtype=np.float32), None

        pts = np.float32([kp.pt for kp in keypoints])
        return pts, descriptors

    def match_descriptors(self, pts_gallery, desc_gallery, pts_probe, desc_probe):
        """
        Matches probe descriptors against a gallery template using FLANN + Lowe ratio test,
        and verifies spatial consistency using RANSAC partial affine estimation.
        Returns the number of geometric inliers.
        """
        if desc_gallery is None or desc_probe is None:
            return 0
        if len(desc_gallery) < 5 or len(desc_probe) < 5:
            return 0

        # FLANN matcher parameters for SIFT
        FLANN_INDEX_KDTREE = 1
        index_params = dict(algorithm=FLANN_INDEX_KDTREE, trees=5)
        search_params = dict(checks=50)

        try:
            flann = cv2.FlannBasedMatcher(index_params, search_params)
            matches = flann.knnMatch(desc_probe, desc_gallery, k=2)
        except Exception:
            return 0

        # Lowe's ratio test
        good_matches = []
        for m_n in matches:
            if len(m_n) == 2:
                m, n = m_n
                if m.distance < 0.78 * n.distance:
                    good_matches.append(m)

        if len(good_matches) < 4:
            return len(good_matches)

        # Geometric verification via RANSAC affine transformation
        if len(pts_gallery) > 0 and len(pts_probe) > 0:
            try:
                matched_probe_pts = pts_probe[[m.queryIdx for m in good_matches]].reshape(-1, 1, 2)
                matched_gallery_pts = pts_gallery[[m.trainIdx for m in good_matches]].reshape(-1, 1, 2)

                _, inliers = cv2.estimateAffinePartial2D(
                    matched_probe_pts,
                    matched_gallery_pts,
                    method=cv2.RANSAC,
                    ransacReprojThreshold=5.0
                )
                if inliers is not None:
                    return int(np.sum(inliers))
            except Exception:
                pass

        return len(good_matches)

    def verify(self, gallery_templates, probe_img):
        """
        Verifies a probe image against a list of enrolled templates.
        Each template in gallery_templates can be:
          - (pts, desc) tuple
          - or just desc (backward compatible)
        Returns: (is_matched: bool, best_score: int)
        """
        pts_probe, desc_probe = self.extract_features(probe_img)
        if desc_probe is None or len(desc_probe) < 5:
            return False, 0

        best_score = 0
        for template in gallery_templates:
            if isinstance(template, tuple) and len(template) == 2:
                pts_gal, desc_gal = template
            else:
                pts_gal, desc_gal = np.empty((0, 2), dtype=np.float32), template

            score = self.match_descriptors(pts_gal, desc_gal, pts_probe, desc_probe)
            if score > best_score:
                best_score = score
            if score >= self.inlier_threshold:
                return True, best_score

        return (best_score >= self.inlier_threshold), best_score
