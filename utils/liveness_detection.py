import cv2
import numpy as np
from collections import deque
from utils.logger import app_logger
import time


class LivenessDetector:
    def __init__(self):
        """Initialize liveness detection"""
        try:
            # Import MediaPipe (compatible with both old and new versions)
            try:
                import mediapipe as mp

                # Try new API first
                if hasattr(mp, 'solutions'):
                    self.mp_face_mesh = mp.solutions.face_mesh
                    self.mp_face_detection = mp.solutions.face_detection

                    self.face_mesh = self.mp_face_mesh.FaceMesh(
                        static_image_mode=False,
                        max_num_faces=1,
                        refine_landmarks=True,
                        min_detection_confidence=0.5,
                        min_tracking_confidence=0.5
                    )

                    self.face_detection = self.mp_face_detection.FaceDetection(
                        min_detection_confidence=0.5
                    )
                else:
                    # Fallback: Use OpenCV for face detection
                    app_logger.warning("MediaPipe solutions not available, using OpenCV fallback")
                    self.use_opencv_fallback = True
                    self.face_cascade = cv2.CascadeClassifier(
                        cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
                    )
                    self.eye_cascade = cv2.CascadeClassifier(
                        cv2.data.haarcascades + 'haarcascade_eye.xml'
                    )

            except ImportError:
                app_logger.warning("MediaPipe not available, using OpenCV fallback")
                self.use_opencv_fallback = True
                self.face_cascade = cv2.CascadeClassifier(
                    cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
                )
                self.eye_cascade = cv2.CascadeClassifier(
                    cv2.data.haarcascades + 'haarcascade_eye.xml'
                )

            # Eye blink detection parameters
            self.EYE_AR_THRESH = 0.25
            self.EYE_AR_CONSEC_FRAMES = 2
            self.blink_counter = 0
            self.blink_total = 0

            # Mouth movement detection
            self.MOUTH_AR_THRESH = 0.6

            # Texture analysis
            self.texture_scores = deque(maxlen=10)

            # Frame buffer
            self.frame_buffer = deque(maxlen=30)

            self.use_opencv_fallback = getattr(self, 'use_opencv_fallback', False)

            app_logger.info("✓ Liveness Detector initialized successfully")

        except Exception as e:
            app_logger.error(f"Failed to initialize Liveness Detector: {e}")
            # Don't raise - fallback to OpenCV
            self.use_opencv_fallback = True
            self.face_cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            )

    def _eye_aspect_ratio(self, landmarks, eye_indices):
        """Calculate eye aspect ratio (EAR)"""
        try:
            eye_points = [landmarks[i] for i in eye_indices]

            v1 = np.linalg.norm(np.array(eye_points[1]) - np.array(eye_points[5]))
            v2 = np.linalg.norm(np.array(eye_points[2]) - np.array(eye_points[4]))
            h = np.linalg.norm(np.array(eye_points[0]) - np.array(eye_points[3]))

            ear = (v1 + v2) / (2.0 * h) if h > 0 else 0.3
            return ear
        except:
            return 0.3

    def _mouth_aspect_ratio(self, landmarks, mouth_indices):
        """Calculate mouth aspect ratio (MAR)"""
        try:
            mouth_points = [landmarks[i] for i in mouth_indices]

            v1 = np.linalg.norm(np.array(mouth_points[1]) - np.array(mouth_points[7]))
            v2 = np.linalg.norm(np.array(mouth_points[2]) - np.array(mouth_points[6]))
            v3 = np.linalg.norm(np.array(mouth_points[3]) - np.array(mouth_points[5]))
            h = np.linalg.norm(np.array(mouth_points[0]) - np.array(mouth_points[4]))

            mar = (v1 + v2 + v3) / (3.0 * h) if h > 0 else 0.3
            return mar
        except:
            return 0.3

    def detect_blink(self, frame):
        """Detect eye blinks"""
        try:
            if self.use_opencv_fallback:
                # Simple blink detection with OpenCV
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                eyes = self.eye_cascade.detectMultiScale(gray, 1.1, 4)

                if len(eyes) < 2:
                    self.blink_counter += 1
                    if self.blink_counter >= self.EYE_AR_CONSEC_FRAMES:
                        self.blink_total += 1
                        self.blink_counter = 0
                        return True, 0.2, 0.2
                else:
                    self.blink_counter = 0

                return False, 0.3, 0.3

            # MediaPipe method
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.face_mesh.process(rgb_frame)

            if not results.multi_face_landmarks:
                return False, 0.0, 0.0

            face_landmarks = results.multi_face_landmarks[0]

            h, w = frame.shape[:2]
            landmarks = []
            for landmark in face_landmarks.landmark:
                landmarks.append([landmark.x * w, landmark.y * h])

            LEFT_EYE = [33, 160, 158, 133, 153, 144]
            RIGHT_EYE = [362, 385, 387, 263, 373, 380]

            left_ear = self._eye_aspect_ratio(landmarks, LEFT_EYE)
            right_ear = self._eye_aspect_ratio(landmarks, RIGHT_EYE)

            avg_ear = (left_ear + right_ear) / 2.0

            blink_detected = False
            if avg_ear < self.EYE_AR_THRESH:
                self.blink_counter += 1
            else:
                if self.blink_counter >= self.EYE_AR_CONSEC_FRAMES:
                    self.blink_total += 1
                    blink_detected = True
                self.blink_counter = 0

            return blink_detected, left_ear, right_ear

        except Exception as e:
            app_logger.error(f"Error in blink detection: {e}")
            return False, 0.0, 0.0

    def detect_mouth_movement(self, frame):
        """Detect mouth opening"""
        try:
            if self.use_opencv_fallback:
                return False, 0.0

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.face_mesh.process(rgb_frame)

            if not results.multi_face_landmarks:
                return False, 0.0

            face_landmarks = results.multi_face_landmarks[0]

            h, w = frame.shape[:2]
            landmarks = []
            for landmark in face_landmarks.landmark:
                landmarks.append([landmark.x * w, landmark.y * h])

            MOUTH = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375]

            mar = self._mouth_aspect_ratio(landmarks, MOUTH)
            mouth_open = mar > self.MOUTH_AR_THRESH

            return mouth_open, mar

        except Exception as e:
            app_logger.error(f"Error in mouth detection: {e}")
            return False, 0.0

    def analyze_texture(self, frame):
        """Analyze image texture"""
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            laplacian = cv2.Laplacian(gray, cv2.CV_64F)
            texture_variance = laplacian.var()

            fft = np.fft.fft2(gray)
            fft_shift = np.fft.fftshift(fft)
            magnitude = np.abs(fft_shift)

            high_freq_energy = np.sum(magnitude[magnitude > np.percentile(magnitude, 90)])

            texture_score = min(1.0, texture_variance / 1000)
            freq_score = min(1.0, high_freq_energy / 1e6)

            combined_score = (texture_score * 0.6 + freq_score * 0.4)

            self.texture_scores.append(combined_score)

            return combined_score

        except Exception as e:
            app_logger.error(f"Error in texture analysis: {e}")
            return 0.5

    def check_screen_reflection(self, frame):
        """Detect screen reflection patterns"""
        try:
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            color_variance = np.var(hsv[:, :, 0])

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            edges = cv2.Canny(gray, 50, 150)
            edge_density = np.sum(edges) / edges.size

            reflection_score = min(1.0, (color_variance / 500) * (1 - edge_density * 10))

            return max(0.0, reflection_score)

        except Exception as e:
            app_logger.error(f"Error in reflection detection: {e}")
            return 0.5

    def comprehensive_liveness_check(self, video_frames, require_blink=True):
        """Comprehensive liveness check"""
        try:
            if len(video_frames) < 10:
                return False, 0.0, {"error": "Insufficient frames"}

            scores = {
                'blink_score': 0.0,
                'texture_score': 0.0,
                'reflection_score': 0.0,
                'motion_score': 0.0,
                'face_quality_score': 0.0
            }

            blink_detected = False
            texture_scores = []
            reflection_scores = []

            for i, frame in enumerate(video_frames):
                if i < len(video_frames) - 5:
                    blinked, left_ear, right_ear = self.detect_blink(frame)
                    if blinked:
                        blink_detected = True

                texture = self.analyze_texture(frame)
                texture_scores.append(texture)

                reflection = self.check_screen_reflection(frame)
                reflection_scores.append(reflection)

            scores['blink_score'] = 1.0 if blink_detected else (0.5 if not require_blink else 0.0)
            scores['texture_score'] = np.mean(texture_scores) if texture_scores else 0.0
            scores['reflection_score'] = np.mean(reflection_scores) if reflection_scores else 0.0

            if len(video_frames) >= 2:
                frame_diffs = []
                for i in range(len(video_frames) - 1):
                    diff = cv2.absdiff(video_frames[i], video_frames[i + 1])
                    frame_diffs.append(np.mean(diff))

                motion_variance = np.var(frame_diffs)
                scores['motion_score'] = min(1.0, motion_variance / 10)

            scores['face_quality_score'] = 0.7

            weights = {
                'blink_score': 0.30,
                'texture_score': 0.25,
                'reflection_score': 0.20,
                'motion_score': 0.15,
                'face_quality_score': 0.10
            }

            overall_confidence = sum(scores[k] * weights[k] for k in weights)

            LIVENESS_THRESHOLD = 0.65
            is_live = overall_confidence >= LIVENESS_THRESHOLD

            details = {
                'scores': scores,
                'overall_confidence': overall_confidence,
                'threshold': LIVENESS_THRESHOLD,
                'blink_detected': blink_detected,
                'frames_analyzed': len(video_frames)
            }

            return is_live, overall_confidence, details

        except Exception as e:
            app_logger.error(f"Error in comprehensive liveness check: {e}")
            return False, 0.0, {"error": str(e)}

    def quick_liveness_check(self, frame):
        """Quick liveness check for single frame"""
        try:
            scores = {}

            texture_score = self.analyze_texture(frame)
            scores['texture'] = texture_score

            reflection_score = self.check_screen_reflection(frame)
            scores['reflection'] = reflection_score

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            sharpness_score = min(1.0, laplacian_var / 500)
            scores['sharpness'] = sharpness_score

            scores['face_confidence'] = 0.7

            overall_score = (
                    texture_score * 0.3 +
                    reflection_score * 0.25 +
                    sharpness_score * 0.25 +
                    scores['face_confidence'] * 0.20
            )

            return overall_score, scores

        except Exception as e:
            app_logger.error(f"Error in quick liveness check: {e}")
            return 0.0, {"error": str(e)}


# Singleton instance
liveness_detector = LivenessDetector()
