'use strict';

/* ============================================================
   QrScanner — shared QR decoding loop (Pinoy Henyo Online)
   ------------------------------------------------------------
   Fixes a real failure mode: the previous implementation awaited
   the native BarcodeDetector BEFORE trying jsQR. On browsers where
   BarcodeDetector.detect() exists but never resolves (several
   Android WebViews / Samsung browsers), the awaited promise starved
   the jsQR fallback forever, so the camera "worked" but a QR code
   was never detected.

   This module:
     * decodes frames with jsQR FIRST (synchronous), so the pure-JS
       decoder always runs regardless of the native API,
     * downscales the frame to <= 640px wide for fast jsQR scans,
     * tries both color polarities (dontInvert, then invertOnly),
     * only then races BarcodeDetector against a 120ms timeout so a
       hanging native detect() can never block future frames,
     * keeps the loop non-overlapping (single in-flight frame).

   Exposed:
     QrScanner.start({ video, onScan })  -> begin scanning a <video>
     QrScanner.stop()                    -> stop scanning
     QrScanner.scanOnce(source)          -> decode one frame (video or
                                            canvas) -> Promise<string|null>
   ============================================================ */

const QrScanner = (() => {
  let _timer = null;
  let _running = false;
  let _canvas = null;

  const MAX_WIDTH = 640;
  const FRAME_DELAY_MS = 90;
  const NATIVE_TIMEOUT_MS = 120;

  function getCanvas() {
    if (_canvas && _canvas.isConnected) return _canvas;
    _canvas = document.createElement('canvas');
    _canvas.id = 'qr-scan-canvas';
    _canvas.hidden = true;
    _canvas.setAttribute('aria-hidden', 'true');
    document.body.appendChild(_canvas);
    return _canvas;
  }

  /* Decode one frame from a <video> or <canvas> source. */
  async function scanOnce(source, maxWidth = MAX_WIDTH) {
    if (!source) return null;
    const srcW = source.videoWidth || source.width || 0;
    const srcH = source.videoHeight || source.height || 0;
    if (!srcW || !srcH) return null;

    const scale = Math.min(1, maxWidth / srcW);
    const w = Math.max(1, Math.round(srcW * scale));
    const h = Math.max(1, Math.round(srcH * scale));

    const canvas = getCanvas();
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) return null;

    try {
      ctx.drawImage(source, 0, 0, w, h);
    } catch (e) {
      return null;
    }

    let imageData;
    try {
      imageData = ctx.getImageData(0, 0, w, h);
    } catch (e) {
      return null;
    }

    // 1) jsQR first — synchronous, never blocked by the native API.
    if (typeof window.jsQR === 'function') {
      for (const inversionAttempts of ['dontInvert', 'invertOnly']) {
        try {
          const code = window.jsQR(imageData.data, w, h, { inversionAttempts });
          if (code && code.data) return code.data;
        } catch (e) { /* keep trying the next strategy */ }
      }
    }

    // 2) Native BarcodeDetector, bounded by a timeout so a hanging
    //    detect() can never starve the loop.
    if (typeof window.BarcodeDetector === 'function') {
      try {
        const detector = getNativeDetector();
        if (detector) {
          const raw = await Promise.race([
            detector.detect(source).then((codes) => {
              for (const c of codes || []) {
                if (c && c.rawValue) return c.rawValue;
              }
              return null;
            }).catch(() => null),
            new Promise((resolve) => setTimeout(() => resolve(null), NATIVE_TIMEOUT_MS)),
          ]);
          if (raw) return raw;
        }
      } catch (e) { /* fall through */ }
    }

    return null;
  }

  let _nativeDetector = null;
  function getNativeDetector() {
    if (!_nativeDetector) {
      try {
        _nativeDetector = new window.BarcodeDetector({ formats: ['qr_code'] });
      } catch (e) {
        _nativeDetector = null;
      }
    }
    return _nativeDetector;
  }

  /* Continuous scanning loop over a live <video> element. */
  function start(opts = {}) {
    const video = opts.video;
    const onScan = opts.onScan;
    stop();
    if (!video || typeof onScan !== 'function') return;

    _running = true;

    let busy = false;
    const process = async () => {
      if (!_running || busy) return;
      if (!video.videoWidth) {
        _timer = setTimeout(process, FRAME_DELAY_MS);
        return;
      }
      busy = true;
      let raw = null;
      try {
        raw = await scanOnce(video);
      } catch (e) {
        raw = null;
      }
      busy = false;
      if (raw && _running) {
        stop();
        onScan(raw);
        return;
      }
      if (_running) _timer = setTimeout(process, FRAME_DELAY_MS);
    };

    _timer = setTimeout(process, FRAME_DELAY_MS);
  }

  function stop() {
    _running = false;
    if (_timer) {
      clearTimeout(_timer);
      _timer = null;
    }
  }

  function isRunning() {
    return _running;
  }

  return {
    start,
    stop,
    scanOnce,
    isRunning,
  };
})();

if (typeof window !== 'undefined') window.QrScanner = QrScanner;