'use strict';
/* ============================================================
   Runtime Configuration — Pinoy Henyo Online (DEPLOYMENT)
   ------------------------------------------------------------
   This plain Vanilla-JS project (HTML/CSS/JS on Vercel) has no
   build step, and Vercel BUILD-TIME environment variables never
   reach the browser. This file is the deployment-safe runtime
   configuration mechanism: it runs BEFORE js/core/config.js and
   seeds window.PINOY_CONFIG, which is the single source of truth
   for backend URLs.

   LOAD ORDER (every page):
     js/core/runtime-config.js   <- this file (optional values)
     js/core/config.js           <- reads window.PINOY_CONFIG
     js/api/api.js               <- REST base = PINOY_CONFIG.API_BASE_URL
     js/api/realtime.js          <- Socket origin = PINOY_CONFIG.SOCKET_BASE_URL

   LOCAL DEVELOPMENT: leave every value as '' (empty). config.js
   auto-detects the same-origin Flask backend on localhost.

   PRODUCTION (Vercel frontend -> Render backend): fill in the
   values below BEFORE deploying, replacing the <RENDER-DOMAIN> /
   <VERCEL-DOMAIN> placeholders with the real origins.

     apiBaseUrl:     origin of the Render backend. May be the bare
                     origin or already end in "/api" — config.js
                     appends "/api" automatically when missing.
                     Example: "https://pinoy-henyo-api.onrender.com"

     socketBaseUrl:  same Render origin. Leave '' to derive it from
                     apiBaseUrl automatically.
                     Example: "https://pinoy-henyo-api.onrender.com"

     qrBaseUrl:      origin players should land on after scanning a
                     QR code — the Vercel FRONTEND origin, never the
                     backend origin. Leave '' to default to the
                     current page origin (correct on Vercel).

     frontendBase:   Vercel frontend origin. Leave '' to default to
                     the current page origin.
   ============================================================ */

window.PINOY_CONFIG = {
  apiBaseUrl:    '',
  socketBaseUrl: '',
  qrBaseUrl:     '',
  frontendBase:  '',
};