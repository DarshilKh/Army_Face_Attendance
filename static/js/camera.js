// Advanced Camera Handling Module

class CameraHandler {
    constructor(videoElementId, canvasElementId) {
        this.video = document.getElementById(videoElementId);
        this.canvas = document.getElementById(canvasElementId);
        this.context = this.canvas ? this.canvas.getContext('2d') : null;
        this.stream = null;
        this.facingMode = 'user'; // 'user' or 'environment'
        this.isActive = false;
        this.constraints = {
            video: {
                width: { ideal: 1280, max: 1920 },
                height: { ideal: 720, max: 1080 },
                facingMode: 'user',
                aspectRatio: { ideal: 1.777 }
            },
            audio: false
        };
    }

    // Start camera
    async start() {
        try {
            // Check if camera is already active
            if (this.isActive) {
                console.log('Camera already active');
                return true;
            }

            // Request camera access
            this.stream = await navigator.mediaDevices.getUserMedia(this.constraints);

            // Set video source
            this.video.srcObject = this.stream;

            // Wait for video to load
            await new Promise((resolve) => {
                this.video.onloadedmetadata = () => {
                    this.video.play();
                    resolve();
                };
            });

            // Update canvas size to match video
            if (this.canvas) {
                this.canvas.width = this.video.videoWidth;
                this.canvas.height = this.video.videoHeight;
            }

            this.isActive = true;
            console.log('Camera started successfully');
            return true;

        } catch (error) {
            console.error('Camera error:', error);

            let errorMessage = 'Unable to access camera. ';

            if (error.name === 'NotAllowedError') {
                errorMessage += 'Please allow camera permissions.';
            } else if (error.name === 'NotFoundError') {
                errorMessage += 'No camera found on this device.';
            } else if (error.name === 'NotReadableError') {
                errorMessage += 'Camera is already in use by another application.';
            } else {
                errorMessage += error.message;
            }

            throw new Error(errorMessage);
        }
    }

    // Stop camera
    stop() {
        if (this.stream) {
            this.stream.getTracks().forEach(track => {
                track.stop();
                console.log('Camera track stopped:', track.kind);
            });

            this.video.srcObject = null;
            this.stream = null;
            this.isActive = false;

            console.log('Camera stopped successfully');
            return true;
        }

        return false;
    }

    // Capture single frame
    captureFrame(quality = 0.95) {
        if (!this.isActive) {
            throw new Error('Camera is not active');
        }

        if (!this.canvas || !this.context) {
            throw new Error('Canvas not initialized');
        }

        // Draw current video frame to canvas
        this.context.drawImage(
            this.video,
            0, 0,
            this.canvas.width,
            this.canvas.height
        );

        // Convert to base64 image
        return this.canvas.toDataURL('image/jpeg', quality);
    }

    // Capture multiple frames
    async captureMultipleFrames(count = 15, intervalMs = 100) {
        if (!this.isActive) {
            throw new Error('Camera is not active');
        }

        return new Promise((resolve, reject) => {
            const frames = [];
            let captured = 0;

            const interval = setInterval(() => {
                try {
                    frames.push(this.captureFrame(0.8));
                    captured++;

                    if (captured >= count) {
                        clearInterval(interval);
                        resolve(frames);
                    }
                } catch (error) {
                    clearInterval(interval);
                    reject(error);
                }
            }, intervalMs);
        });
    }

    // Switch camera (front/back)
    async switchCamera() {
        this.facingMode = this.facingMode === 'user' ? 'environment' : 'user';
        this.constraints.video.facingMode = this.facingMode;

        if (this.isActive) {
            this.stop();
            await this.start();
        }
    }

    // Get camera capabilities
    getCapabilities() {
        if (!this.stream) {
            return null;
        }

        const videoTrack = this.stream.getVideoTracks()[0];
        if (videoTrack) {
            return videoTrack.getCapabilities();
        }

        return null;
    }

    // Get current settings
    getSettings() {
        if (!this.stream) {
            return null;
        }

        const videoTrack = this.stream.getVideoTracks()[0];
        if (videoTrack) {
            return videoTrack.getSettings();
        }

        return null;
    }

    // Draw face detection box
    drawFaceBox(x, y, width, height, color = '#00FF00') {
        if (!this.canvas || !this.context) {
            return;
        }

        this.context.strokeStyle = color;
        this.context.lineWidth = 3;
        this.context.strokeRect(x, y, width, height);
    }

    // Draw landmarks (eyes, nose, mouth)
    drawLandmarks(landmarks, color = '#FF0000') {
        if (!this.canvas || !this.context) {
            return;
        }

        this.context.fillStyle = color;
        landmarks.forEach(point => {
            this.context.beginPath();
            this.context.arc(point.x, point.y, 3, 0, 2 * Math.PI);
            this.context.fill();
        });
    }

    // Clear canvas
    clearCanvas() {
        if (this.canvas && this.context) {
            this.context.clearRect(0, 0, this.canvas.width, this.canvas.height);
        }
    }

    // Check if camera is active
    isRunning() {
        return this.isActive;
    }

    // Take snapshot and download
    downloadSnapshot(filename = 'snapshot.jpg') {
        const imageData = this.captureFrame(0.95);

        const link = document.createElement('a');
        link.href = imageData;
        link.download = filename;
        link.click();
    }
}

// Camera Utilities
class CameraUtils {
    // Check if device has camera
    static async hasCamera() {
        try {
            const devices = await navigator.mediaDevices.enumerateDevices();
            return devices.some(device => device.kind === 'videoinput');
        } catch (error) {
            console.error('Error checking camera:', error);
            return false;
        }
    }

    // Get list of available cameras
    static async getCameraList() {
        try {
            const devices = await navigator.mediaDevices.enumerateDevices();
            return devices.filter(device => device.kind === 'videoinput');
        } catch (error) {
            console.error('Error getting camera list:', error);
            return [];
        }
    }

    // Check camera permissions
    static async checkPermissions() {
        try {
            const result = await navigator.permissions.query({ name: 'camera' });
            return result.state; // 'granted', 'denied', or 'prompt'
        } catch (error) {
            console.error('Error checking permissions:', error);
            return 'unknown';
        }
    }
}

// Export for use
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { CameraHandler, CameraUtils };
}
