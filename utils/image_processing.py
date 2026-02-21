import cv2
import numpy as np
from PIL import Image
import os
from utils.logger import app_logger


def preprocess_image(image_path, target_size=(640, 640)):
    """Preprocess image for face recognition"""
    try:
        image = cv2.imread(image_path)
        if image is None:
            return None

        # Resize if needed
        h, w = image.shape[:2]
        if h > target_size[0] or w > target_size[1]:
            image = cv2.resize(image, target_size, interpolation=cv2.INTER_AREA)

        return image
    except Exception as e:
        app_logger.error(f"Error preprocessing image: {e}")
        return None


def enhance_face_image(image):
    """Enhance image quality for better recognition"""
    try:
        # Convert to LAB color space
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)

        # Apply CLAHE to L channel
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        l = clahe.apply(l)

        # Merge channels
        enhanced = cv2.merge([l, a, b])
        enhanced = cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)

        # Denoise
        enhanced = cv2.fastNlMeansDenoisingColored(enhanced, None, 10, 10, 7, 21)

        return enhanced
    except Exception as e:
        app_logger.error(f"Error enhancing image: {e}")
        return image


def align_face(image, face_landmarks):
    """Align face for better recognition accuracy"""
    try:
        # Get left and right eye coordinates
        left_eye = face_landmarks[0]
        right_eye = face_landmarks[1]

        # Calculate angle
        dY = right_eye[1] - left_eye[1]
        dX = right_eye[0] - left_eye[0]
        angle = np.degrees(np.arctan2(dY, dX))

        # Get center point between eyes
        eye_center = ((left_eye[0] + right_eye[0]) // 2, (left_eye[1] + right_eye[1]) // 2)

        # Rotation matrix
        M = cv2.getRotationMatrix2D(eye_center, angle, 1.0)

        # Apply rotation
        aligned = cv2.warpAffine(image, M, (image.shape[1], image.shape[0]), flags=cv2.INTER_CUBIC)

        return aligned
    except Exception as e:
        app_logger.error(f"Error aligning face: {e}")
        return image


def save_upload_image(file, upload_folder, filename):
    """Save uploaded image securely"""
    try:
        os.makedirs(upload_folder, exist_ok=True)
        filepath = os.path.join(upload_folder, filename)
        file.save(filepath)
        return filepath
    except Exception as e:
        app_logger.error(f"Error saving image: {e}")
        return None


def crop_face_region(image, bbox, padding=0.2):
    """Crop face region with padding"""
    try:
        h, w = image.shape[:2]
        x1, y1, x2, y2 = bbox

        # Add padding
        pad_w = int((x2 - x1) * padding)
        pad_h = int((y2 - y1) * padding)

        x1 = max(0, x1 - pad_w)
        y1 = max(0, y1 - pad_h)
        x2 = min(w, x2 + pad_w)
        y2 = min(h, y2 + pad_h)

        cropped = image[y1:y2, x1:x2]
        return cropped
    except Exception as e:
        app_logger.error(f"Error cropping face: {e}")
        return image
