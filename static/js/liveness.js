// Liveness Detection JavaScript Module

class LivenessDetector {
    constructor() {
        this.frames = [];
        this.maxFrames = 15;
        this.captureInterval = 100; // ms
        this.isCapturing = false;
        this.blinkDetected = false;
        this.callbacks = {
            onProgress: null,
            onComplete: null,
            onError: null
        };
    }

    // Start liveness detection
    async start(videoElement, callbacks = {}) {
        this.callbacks = { ...this.callbacks, ...callbacks };
        this.frames = [];
        this.isCapturing = true;
        this.blinkDetected = false;

        try {
            await this.captureFrames(videoElement);
        } catch (error) {
            if (this.callbacks.onError) {
                this.callbacks.onError(error);
            }
        }
    }

    // Capture multiple frames
    async captureFrames(videoElement) {
        return new Promise((resolve, reject) => {
            let capturedCount = 0;

            const canvas = document.createElement('canvas');
            canvas.width = videoElement.videoWidth;
            canvas.height = videoElement.videoHeight;
            const context = canvas.getContext('2d');

            const interval = setInterval(() => {
                if (!this.isCapturing || capturedCount >= this.maxFrames) {
                    clearInterval(interval);

                    if (capturedCount >= this.maxFrames) {
                        if (this.callbacks.onComplete) {
                            this.callbacks.onComplete(this.frames);
                        }
                        resolve(this.frames);
                    } else {
                        reject(new Error('Capture stopped before completion'));
                    }
                    return;
                }

                // Draw current frame
                context.drawImage(videoElement, 0, 0, canvas.width, canvas.height);

                // Convert to base64
                const frameData = canvas.toDataURL('image/jpeg', 0.8);
                this.frames.push(frameData);

                capturedCount++;

                // Update progress
                const progress = (capturedCount / this.maxFrames) * 100;
                if (this.callbacks.onProgress) {
                    this.callbacks.onProgress(progress, capturedCount);
                }

            }, this.captureInterval);
        });
    }

    // Stop capturing
    stop() {
        this.isCapturing = false;
    }

    // Analyze frames for blink detection (client-side)
    analyzeFrames() {
        // This is a simplified version
        // Real detection happens on server side
        const frameCount = this.frames.length;

        if (frameCount >= 10) {
            // Assume blink if we have enough frames
            this.blinkDetected = true;
            return {
                success: true,
                framesAnalyzed: frameCount,
                blinkDetected: this.blinkDetected
            };
        }

        return {
            success: false,
            framesAnalyzed: frameCount,
            blinkDetected: false,
            message: 'Insufficient frames for analysis'
        };
    }

    // Get captured frames
    getFrames() {
        return this.frames;
    }

    // Reset detector
    reset() {
        this.frames = [];
        this.isCapturing = false;
        this.blinkDetected = false;
    }
}

// Blink Detection Helper
class BlinkDetector {
    constructor() {
        this.eyeClosedFrames = 0;
        this.blinkThreshold = 3;
        this.totalBlinks = 0;
    }

    // Process frame for blink detection
    processFrame(eyeAspectRatio) {
        const EYE_AR_THRESH = 0.25;

        if (eyeAspectRatio < EYE_AR_THRESH) {
            this.eyeClosedFrames++;
        } else {
            if (this.eyeClosedFrames >= this.blinkThreshold) {
                this.totalBlinks++;
                this.eyeClosedFrames = 0;
                return true; // Blink detected
            }
            this.eyeClosedFrames = 0;
        }

        return false;
    }

    getTotalBlinks() {
        return this.totalBlinks;
    }

    reset() {
        this.eyeClosedFrames = 0;
        this.totalBlinks = 0;
    }
}

// Movement Detection
class MovementDetector {
    constructor() {
        this.previousFrame = null;
        this.movementThreshold = 10;
    }

    // Detect movement between frames
    detectMovement(currentFrame) {
        if (!this.previousFrame) {
            this.previousFrame = currentFrame;
            return 0;
        }

        // Simple pixel difference calculation
        // In real implementation, use more sophisticated algorithms
        const movement = this.calculateFrameDifference(this.previousFrame, currentFrame);
        this.previousFrame = currentFrame;

        return movement;
    }

    calculateFrameDifference(frame1, frame2) {
        // Simplified calculation
        // Real implementation would use OpenCV-like algorithms
        return Math.random() * 20; // Placeholder
    }

    reset() {
        this.previousFrame = null;
    }
}

// Export for use in other scripts
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { LivenessDetector, BlinkDetector, MovementDetector };
}
