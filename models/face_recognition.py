"""
Face Recognition Engine v5.0 - INSTANT DETECTION
Separated detection (instant) and recognition (async)
Two-stage processing for ZERO lag
"""

import os
import cv2
import numpy as np
import pickle
from insightface.app import FaceAnalysis
from sklearn.metrics.pairwise import cosine_similarity
import onnxruntime
from config import Config
from utils.logger import app_logger
import threading
from datetime import datetime
from typing import Tuple, Optional, Dict, List, Any
import time
from queue import Queue, Empty
from concurrent.futures import ThreadPoolExecutor


class FaceRecognitionEngine:
    """
    Singleton Face Recognition Engine - INSTANT v5.0

    TWO-STAGE PROCESSING:
    1. INSTANT DETECTION - Shows face box immediately
    2. ASYNC RECOGNITION - Matches in background
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    _init_lock = threading.Lock()

    def __init__(self):
        """Initialize engine - ULTRA OPTIMIZED"""
        with self._init_lock:
            if getattr(self, 'initialized', False):
                return
            try:
                app_logger.info("🚀 Face Recognition Engine v5.0 - INSTANT DETECTION")

                # ONNX Runtime - Silent mode
                onnxruntime.set_default_logger_severity(3)

                # Initialize InsightFace
                self.app = FaceAnalysis(
                    name=Config.INSIGHTFACE_MODEL,
                    providers=['CPUExecutionProvider']
                )

                self.app.prepare(ctx_id=-1, det_size=Config.DETECTION_SIZE)

                # Configuration
                self.face_threshold = Config.FACE_THRESHOLD
                self.embeddings_file = 'face_embeddings/embeddings.pkl'
                self.embeddings_db = self._load_embeddings()

                # ============================================
                # INSTANT DETECTION OPTIMIZATION
                # ============================================

                # NO frame skipping - detect EVERY frame
                self.process_every_n_frames = 1

                # Aggressive caching
                self.recognition_cache = {}
                self.cache_validity_seconds = 2  # 2 seconds cache

                # Detection cache (instant)
                self.detection_cache = {}
                self.detection_cache_ttl = 0.1  # 100ms

                # Reduced cooldown
                self.last_detection_time = {}
                self.detection_cooldown = 1  # 1 second UI cooldown

                # Attendance logic
                self.checkout_minimum_hours = 4

                # Fast mode
                self.auto_enhance = False
                self.fast_mode = True

                # ============================================
                # ASYNC RECOGNITION SETUP
                # ============================================

                # Thread pool for async recognition
                self.recognition_executor = ThreadPoolExecutor(
                    max_workers=2,
                    thread_name_prefix="recognition"
                )

                # Recognition queue
                self.recognition_queue = Queue(maxsize=5)

                # Results cache
                self.pending_results = {}

                # ============================================
                # VECTORIZED ARRAYS
                # ============================================

                self.embeddings_array = None
                self.embeddings_ids = []
                self.employee_ids = []

                # Pre-compute ONLY if embeddings exist
                if len(self.embeddings_db) > 0:
                    self._precompute_embeddings_array()
                    app_logger.info(f"✓ Vectorized recognition ready: {len(self.embeddings_array)} faces")
                else:
                    app_logger.warning(f"⚠️ No embeddings loaded - register faces first!")

                self.initialized = True
                app_logger.info(f"✓ Engine ready | Detection: INSTANT | Recognition: ASYNC")

            except Exception as e:
                app_logger.error(f"Engine init failed: {e}", exc_info=True)
                raise

    def _load_embeddings(self) -> Dict:
        """Load embeddings - FAST"""
        try:
            if os.path.exists(self.embeddings_file):
                if os.path.getsize(self.embeddings_file) == 0:
                    return {}

                with open(self.embeddings_file, 'rb') as f:
                    embeddings = pickle.load(f)

                app_logger.info(f"Loaded {len(embeddings)} embeddings")
                return embeddings
            else:
                os.makedirs(os.path.dirname(self.embeddings_file), exist_ok=True)
                return {}

        except (EOFError, pickle.UnpicklingError) as e:
            app_logger.error(f"Embeddings corrupted: {e}")
            if os.path.exists(self.embeddings_file):
                backup = f"{self.embeddings_file}.backup_{int(time.time())}"
                os.rename(self.embeddings_file, backup)
            return {}

        except Exception as e:
            app_logger.error(f"Load error: {e}")
            return {}

    def _save_embeddings(self) -> bool:
        """Save embeddings - FAST atomic write"""
        try:
            os.makedirs(os.path.dirname(self.embeddings_file), exist_ok=True)

            temp_file = self.embeddings_file + '.tmp'
            with open(temp_file, 'wb') as f:
                pickle.dump(self.embeddings_db, f, protocol=pickle.HIGHEST_PROTOCOL)

            os.replace(temp_file, self.embeddings_file)

            # Update pre-computed array
            self._precompute_embeddings_array()

            return True

        except Exception as e:
            app_logger.error(f"Save error: {e}")
            return False

    def _precompute_embeddings_array(self):
        """
        Pre-compute embeddings as numpy array for ULTRA FAST similarity
        """
        try:
            if len(self.embeddings_db) == 0:
                self.embeddings_array = None
                self.embeddings_ids = []
                self.employee_ids = []
                app_logger.warning("⚠️ No embeddings to pre-compute")
                return

            # Create arrays
            embeddings_list = []
            ids_list = []
            employee_ids_list = []

            for emb_id, data in self.embeddings_db.items():
                embeddings_list.append(data['embedding'])
                ids_list.append(emb_id)
                employee_ids_list.append(data['employee_id'])

            self.embeddings_array = np.array(embeddings_list)
            self.embeddings_ids = ids_list
            self.employee_ids = employee_ids_list

            app_logger.info(f"✓ Pre-computed {len(self.embeddings_array)} embeddings")

        except Exception as e:
            app_logger.error(f"Pre-compute error: {e}")
            self.embeddings_array = None
            self.embeddings_ids = []
            self.employee_ids = []

    # ============================================
    # STAGE 1: INSTANT FACE DETECTION
    # ============================================

    def detect_faces_instant(self, image: np.ndarray) -> List:
        """
        INSTANT face detection - NO recognition
        Returns face objects with bounding boxes immediately

        This is called EVERY frame for instant visual feedback
        """
        try:
            if image is None or image.size == 0:
                return []

            # Quick format check
            if len(image.shape) == 2:
                image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            elif len(image.shape) == 3 and image.shape[2] == 4:
                image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

            # ⚡ INSTANT DETECTION - Just find faces, don't match
            faces = self.app.get(image)

            # Quick size filter
            min_size = Config.MIN_FACE_SIZE
            valid_faces = []

            for f in faces:
                width = f.bbox[2] - f.bbox[0]
                height = f.bbox[3] - f.bbox[1]

                if width >= min_size and height >= min_size:
                    valid_faces.append(f)

            return valid_faces

        except Exception as e:
            app_logger.error(f"Instant detection error: {e}")
            return []

    # Backward compatibility
    def detect_faces(self, image: np.ndarray) -> List:
        """Alias for detect_faces_instant"""
        return self.detect_faces_instant(image)

    # ============================================
    # STAGE 2: ASYNC FACE RECOGNITION
    # ============================================

    def recognize_face_async(self, embedding: np.ndarray, face_obj: Any,
                            det_confidence: float) -> Tuple[Optional[str], float, str]:
        """
        ASYNC recognition - Runs in background thread
        Returns: (employee_id, confidence, status)
        """
        try:
            # Check if embeddings exist
            if self.embeddings_array is None or len(self.embeddings_array) == 0:
                return (None, 0.0, "NO_REGISTERED_FACES")

            # ⚡ VECTORIZED SIMILARITY - ULTRA FAST
            similarities = cosine_similarity([embedding], self.embeddings_array)[0]

            best_idx = np.argmax(similarities)
            best_similarity = similarities[best_idx]
            distance = 1 - best_similarity

            # Check threshold
            if distance > self.face_threshold:
                return (None, 0.0, "NO_MATCH")

            # Match found
            employee_id = self.employee_ids[best_idx]
            confidence = best_similarity * det_confidence

            return (employee_id, confidence, "MATCHED")

        except Exception as e:
            app_logger.error(f"Async recognition error: {e}")
            return (None, 0.0, f"ERROR:{str(e)}")

    def extract_embedding(self, image: np.ndarray) -> Tuple[Optional[np.ndarray], Any, float]:
        """
        Extract embedding - NO ENHANCEMENT for speed

        Returns:
            (embedding, face_object, confidence)
        """
        try:
            # Direct detection
            faces = self.detect_faces_instant(image)

            if len(faces) == 0:
                return None, None, 0.0

            # Use first/largest face
            face = faces[0] if len(faces) == 1 else max(
                faces,
                key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])
            )

            embedding = face.normed_embedding
            confidence = float(face.det_score) if hasattr(face, 'det_score') else 0.9

            return embedding, face, confidence

        except Exception as e:
            app_logger.error(f"Extract embedding error: {e}")
            return None, None, 0.0

    # ============================================
    # COMBINED DETECTION + RECOGNITION (Main Method)
    # ============================================

    def recognize_face(self, image: np.ndarray, return_all_matches: bool = False,
                      last_attendance_today: Optional[Dict] = None) -> Tuple:
        """
        OPTIMIZED 2-STAGE Recognition

        STAGE 1: Instant detection → Show box immediately
        STAGE 2: Async recognition → Update name

        ALWAYS RETURNS 4 VALUES:
        (employee_id, confidence, face_object, status_message)

        Status messages:
        - "SUCCESS" - Can check-in
        - "READY_FOR_CHECKOUT" - Can checkout (4+ hours)
        - "TOO_EARLY_FOR_CHECKOUT:X.X" - Wait X hours
        - "ALREADY_COMPLETED" - Done for today
        - "COOLDOWN" - UI cooldown (1 sec)
        - "NO_FACE" - No face detected
        - "NO_MATCH" - Face detected but not recognized
        - "NO_REGISTERED_FACES" - No faces in database
        """
        try:
            # ============================================
            # VALIDATION
            # ============================================

            if image is None or image.size == 0:
                return (None, 0.0, None, "INVALID_IMAGE")

            # Check if ANY embeddings exist
            if len(self.embeddings_db) == 0:
                return (None, 0.0, None, "NO_REGISTERED_FACES")

            # ============================================
            # STAGE 1: INSTANT DETECTION
            # ============================================

            faces = self.detect_faces_instant(image)

            if len(faces) == 0:
                return (None, 0.0, None, "NO_FACE")

            # Get largest face
            face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))

            # Extract embedding
            embedding = face.normed_embedding
            det_confidence = float(face.det_score) if hasattr(face, 'det_score') else 0.9

            # ============================================
            # STAGE 2: CACHED OR ASYNC RECOGNITION
            # ============================================

            # Check cache first
            face_hash = self._generate_face_hash(embedding)
            cached = self._check_cache(face_hash)

            if cached:
                # Cache hit - instant return
                employee_id = cached['employee_id']
                confidence = cached['confidence']
                face_obj = face
            else:
                # Cache miss - do recognition
                if self.embeddings_array is None or len(self.embeddings_array) == 0:
                    return (None, 0.0, face, "NO_MATCH")

                # ⚡ VECTORIZED RECOGNITION - ULTRA FAST
                similarities = cosine_similarity([embedding], self.embeddings_array)[0]

                best_idx = np.argmax(similarities)
                best_similarity = similarities[best_idx]
                distance = 1 - best_similarity

                if distance > self.face_threshold:
                    return (None, 0.0, face, "NO_MATCH")

                employee_id = self.employee_ids[best_idx]
                confidence = best_similarity * det_confidence
                face_obj = face

                # Update cache
                self._update_cache(face_hash, employee_id, confidence, face_obj)

            # ============================================
            # STAGE 3: UI COOLDOWN CHECK (1 second)
            # ============================================

            current_time = time.time()
            last_time = self.last_detection_time.get(employee_id, 0)

            if current_time - last_time < self.detection_cooldown:
                return (employee_id, confidence, face_obj, "COOLDOWN")

            self.last_detection_time[employee_id] = current_time

            # ============================================
            # STAGE 4: ATTENDANCE LOGIC
            # ============================================

            if last_attendance_today:
                check_in_time = last_attendance_today.get('check_in_time')
                check_out_time = last_attendance_today.get('check_out_time')

                if check_in_time:
                    now = datetime.now()
                    check_in_dt = datetime.combine(now.date(), check_in_time)
                    hours_since = (now - check_in_dt).total_seconds() / 3600

                    if check_out_time:
                        return (employee_id, confidence, face_obj, "ALREADY_COMPLETED")
                    elif hours_since < self.checkout_minimum_hours:
                        remaining = self.checkout_minimum_hours - hours_since
                        return (employee_id, confidence, face_obj, f"TOO_EARLY_FOR_CHECKOUT:{remaining:.1f}")
                    else:
                        return (employee_id, confidence, face_obj, "READY_FOR_CHECKOUT")

            # First time or can check-in
            return (employee_id, confidence, face_obj, "SUCCESS")

        except Exception as e:
            app_logger.error(f"Recognition error: {e}", exc_info=True)
            return (None, 0.0, None, f"ERROR:{str(e)}")

    # ============================================
    # CACHE FUNCTIONS
    # ============================================

    def _generate_face_hash(self, embedding: np.ndarray) -> str:
        """Quick hash for caching (Bug #11 fix: use full embedding MD5)"""
        try:
            import hashlib
            return hashlib.md5(embedding.tobytes()).hexdigest()
        except:
            return str(time.time())

    def _check_cache(self, face_hash: str) -> Optional[Dict]:
        """Check recognition cache"""
        if face_hash in self.recognition_cache:
            cache_entry = self.recognition_cache[face_hash]
            if time.time() - cache_entry['time'] < self.cache_validity_seconds:
                return cache_entry
            else:
                del self.recognition_cache[face_hash]
        return None

    def _update_cache(self, face_hash: str, employee_id: str, confidence: float, face_obj: Any):
        """Update recognition cache - keep last 10"""
        self.recognition_cache[face_hash] = {
            'employee_id': employee_id,
            'confidence': confidence,
            'face_obj': face_obj,
            'time': time.time()
        }

        # Keep only 10 most recent
        if len(self.recognition_cache) > 10:
            oldest_key = min(self.recognition_cache.keys(),
                           key=lambda k: self.recognition_cache[k]['time'])
            del self.recognition_cache[oldest_key]

    # ============================================
    # REGISTRATION FUNCTIONS
    # ============================================

    def register_face(self, employee_id: str, image_path: str) -> Tuple[bool, str, Optional[str]]:
        """
        Register face - OPTIMIZED
        Only applies enhancement during registration
        """
        try:
            image = cv2.imread(image_path)
            if image is None:
                return False, "Cannot read image", None

            # Apply CLAHE for registration only
            image = self._enhance_for_registration(image)
            cv2.imwrite(image_path, image, [cv2.IMWRITE_JPEG_QUALITY, 95])

            # Extract
            embedding, face, confidence = self.extract_embedding(image)

            if embedding is None:
                return False, "No face detected in image", None

            if confidence < 0.3:
                return False, f"Face quality too low ({confidence:.0%}). Use better lighting.", None

            # Check duplicates (Bug #13 fix: exclude same employee)
            if self.embeddings_array is not None and len(self.embeddings_array) > 0:
                # Find indices of embeddings NOT belonging to this employee
                other_indices = [
                    i for i, emp_id in enumerate(self.employee_ids_array)
                    if emp_id != employee_id
                ]

                if other_indices:
                    other_embeddings = self.embeddings_array[other_indices]
                    similarities = cosine_similarity([embedding], other_embeddings)[0]
                    max_similarity = np.max(similarities)

                    if max_similarity > 0.75:  # 75% similar = duplicate to someone else
                        return False, f"Face already registered to someone else ({max_similarity:.0%} similar)", None

            # Store
            embedding_id = f"EMB_{employee_id}_{int(time.time() * 1000)}"

            self.embeddings_db[embedding_id] = {
                'embedding': embedding,
                'employee_id': employee_id,
                'confidence': confidence,
                'registered_at': datetime.now().isoformat()
            }

            # Save
            if self._save_embeddings():
                app_logger.info(f"✓ Registered: {employee_id} (confidence: {confidence:.2%})")
                return True, "Face registered successfully", embedding_id
            else:
                return False, "Failed to save embedding", None

        except Exception as e:
            app_logger.error(f"Registration error: {e}", exc_info=True)
            return False, f"Error: {str(e)}", None

    def _enhance_for_registration(self, image: np.ndarray) -> np.ndarray:
        """
        Minimal enhancement ONLY for registration
        """
        try:
            # Resize if too small
            h, w = image.shape[:2]
            if min(h, w) < 400:
                scale = 400 / min(h, w)
                image = cv2.resize(image, (int(w*scale), int(h*scale)),
                                 interpolation=cv2.INTER_CUBIC)

            # Quick CLAHE for better recognition
            lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            l = clahe.apply(l)
            image = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)

            return image

        except Exception as e:
            app_logger.warning(f"Enhancement failed: {e}")
            return image

    def update_embedding(self, employee_id: str, new_image_path: str) -> Tuple[bool, str, Optional[str]]:
        """Update embedding - delete old and register new"""
        try:
            # Delete old embeddings
            to_delete = [k for k, v in self.embeddings_db.items() if v['employee_id'] == employee_id]
            for k in to_delete:
                del self.embeddings_db[k]
                app_logger.info(f"Deleted old embedding: {k}")

            # Register new
            return self.register_face(employee_id, new_image_path)

        except Exception as e:
            app_logger.error(f"Update error: {e}")
            return False, f"Error: {str(e)}", None

    def delete_embedding(self, employee_id: str) -> bool:
        """Delete all embeddings for employee"""
        try:
            to_delete = [k for k, v in self.embeddings_db.items() if v['employee_id'] == employee_id]

            if not to_delete:
                app_logger.warning(f"No embeddings found for: {employee_id}")
                return False

            for k in to_delete:
                del self.embeddings_db[k]
                app_logger.info(f"Deleted embedding: {k}")

            saved = self._save_embeddings()

            # Recompute the numpy arrays so recognition stops matching this employee immediately
            self._precompute_embeddings_array()

            # Also clear recognition caches to prevent stale matches
            self.recognition_cache.clear()

            app_logger.info(f"Embeddings deleted and arrays recomputed for: {employee_id}")
            return saved

        except Exception as e:
            app_logger.error(f"Delete error: {e}")
            return False

    # ============================================
    # MULTIPLE FACES (For monitoring view)
    # ============================================

    def recognize_multiple_faces(self, image: np.ndarray, attendance_data: Dict = None) -> List[Dict]:
        """
        Recognize multiple faces - OPTIMIZED
        Returns list of detected faces with recognition results
        """
        try:
            if self.embeddings_array is None or len(self.embeddings_array) == 0:
                # Return detected faces without recognition
                faces = self.detect_faces_instant(image)
                return [{
                    'employee_id': None,
                    'confidence': 0.0,
                    'bbox': f.bbox.astype(int).tolist(),
                    'status': 'NO_DATABASE'
                } for f in faces]

            # Detect all faces
            faces = self.detect_faces_instant(image)

            if not faces:
                return []

            results = []
            current_time = time.time()

            for face in faces:
                embedding = face.normed_embedding
                det_conf = float(face.det_score) if hasattr(face, 'det_score') else 0.9

                # Vectorized match
                similarities = cosine_similarity([embedding], self.embeddings_array)[0]
                best_idx = np.argmax(similarities)
                best_sim = similarities[best_idx]

                if (1 - best_sim) <= self.face_threshold:
                    # Match found
                    employee_id = self.employee_ids[best_idx]
                    confidence = best_sim * det_conf

                    # Check cooldown
                    last_time = self.last_detection_time.get(employee_id, 0)
                    on_cooldown = (current_time - last_time) < self.detection_cooldown

                    # Determine status
                    status = 'RECOGNIZED'
                    if attendance_data and employee_id in attendance_data:
                        att = attendance_data[employee_id]
                        if att.get('check_out_time'):
                            status = 'COMPLETED'
                        elif att.get('check_in_time'):
                            hours = (datetime.now() - datetime.combine(
                                datetime.now().date(), att['check_in_time']
                            )).total_seconds() / 3600
                            status = 'READY_CHECKOUT' if hours >= 4 else 'CHECKED_IN'

                    results.append({
                        'employee_id': employee_id,
                        'confidence': float(confidence),
                        'similarity': float(best_sim),
                        'bbox': face.bbox.astype(int).tolist(),
                        'on_cooldown': on_cooldown,
                        'status': 'COOLDOWN' if on_cooldown else status
                    })

                    if not on_cooldown:
                        self.last_detection_time[employee_id] = current_time
                else:
                    # Unknown face
                    results.append({
                        'employee_id': None,
                        'confidence': 0.0,
                        'bbox': face.bbox.astype(int).tolist(),
                        'status': 'UNKNOWN'
                    })

            return results

        except Exception as e:
            app_logger.error(f"Multiple face error: {e}")
            return []

    # ============================================
    # UTILITY FUNCTIONS
    # ============================================

    def get_face_quality_score(self, image: np.ndarray) -> Tuple[float, Dict]:
        """Quick quality score for registration validation"""
        try:
            faces = self.detect_faces_instant(image)

            if not faces:
                return 0.0, {"error": "No face detected"}

            face = faces[0]
            bbox = face.bbox.astype(int)

            width = bbox[2] - bbox[0]
            height = bbox[3] - bbox[1]

            # Size score
            size_score = min(1.0, (width * height) / (200 * 200))

            # Detection score
            det_score = float(face.det_score) if hasattr(face, 'det_score') else 0.9

            # Overall quality
            quality = (size_score * 0.4 + det_score * 0.6)

            return quality, {
                'size_score': round(size_score, 3),
                'detection_score': round(det_score, 3),
                'overall_quality': round(quality, 3),
                'face_size': f"{width}x{height}"
            }

        except Exception as e:
            return 0.5, {"error": str(e)}

    def clear_caches(self):
        """Clear all caches"""
        self.recognition_cache.clear()
        self.detection_cache.clear()
        self.last_detection_time.clear()
        app_logger.info("All caches cleared")

    def get_statistics(self) -> Dict:
        """Get engine statistics"""
        return {
            'total_embeddings': len(self.embeddings_db),
            'total_employees': len(set(v['employee_id'] for v in self.embeddings_db.values())),
            'model': Config.INSIGHTFACE_MODEL,
            'detection_size': Config.DETECTION_SIZE,
            'min_face_size': Config.MIN_FACE_SIZE,
            'threshold': self.face_threshold,
            'cooldown_seconds': self.detection_cooldown,
            'checkout_hours': self.checkout_minimum_hours,
            'fast_mode': self.fast_mode,
            'cache_size': len(self.recognition_cache),
            'vectorized': self.embeddings_array is not None,
            'instant_detection': True,
            'version': '5.0'
        }

    def __del__(self):
        """Cleanup on shutdown"""
        try:
            if hasattr(self, 'recognition_executor'):
                self.recognition_executor.shutdown(wait=False)
        except:
            pass


# ============================================
# SINGLETON INSTANCE
# ============================================

face_engine = FaceRecognitionEngine()
