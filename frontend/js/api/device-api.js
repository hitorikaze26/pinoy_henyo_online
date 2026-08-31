'use strict';

/* ============================================================
   Device / Session API — /api/devices
   Handles a device's session token + heartbeat.
   The stable device id is owned by API.getDeviceId() so it
   survives page refreshes and reconnect attempts.
   ============================================================ */

const DeviceAPI = (() => {
  function getDeviceId() {
    return API.getDeviceId();
  }

  // POST /api/devices/connect  { connection_token?, session_token?, device_id }
  // - With a `connection_token` (from create/join/add-member): establishes a
  //   brand-new device session for that member.
  // - With a `session_token` (persisted, same device): RE-CONNECTS / restores
  //   the existing session (clears disconnected_at, marks connected).
  // The returned session payload contains game_id, team_id, member_id,
  // and device_type. We store that identity for cross-page restoration.
  async function connect({ connectionToken } = {}) {
    const body = { device_id: getDeviceId() };
    const existing = API.getSessionToken();
    if (existing) body.session_token = existing;
    if (connectionToken) body.connection_token = connectionToken;
    const data = await API.request('/devices/connect', { method: 'POST', body });

    if (data && data.session_token) {
      API.setSessionToken(data.session_token);
      if (data.game_id) API.setGameId(data.game_id);
      if (data.team_id) API.setTeamId(data.team_id);
      if (data.member_id) API.setMemberId(data.member_id);
      if (data.device_type === 'TEAM_LEADER') { API.setRole('team-leader'); API.setDeviceRole('TEAM_LEADER'); }
      else if (data.device_type === 'TEAM_MEMBER') { API.setRole('team-member'); API.setDeviceRole('TEAM_MEMBER'); }
    }
    return data;
  }

  // Attempt to restore + reconnect using the persisted session token.
  // Resolves { connected: true, data } on success, or
  //        { connected: false, error } if there is no session/invalid.
  async function reconnect() {
    const token = API.getSessionToken();
    if (!token) return { connected: false, error: { code: 'NO_SESSION' } };
    try {
      const data = await connect({});
      return { connected: true, data };
    } catch (err) {
      return { connected: false, error: err };
    }
  }

  function hasSession() {
    return !!API.getSessionToken();
  }

  // POST /api/devices/heartbeat — keep the session alive.
  function heartbeat() {
    const token = API.getSessionToken();
    if (!token) return Promise.resolve(null);
    return API.request('/devices/heartbeat', {
      method: 'POST',
      body: { session_token: token, device_id: getDeviceId() },
    });
  }

  // POST /api/devices/disconnect
  function disconnect() {
    const token = API.getSessionToken();
    if (!token) return Promise.resolve(null);
    return API.request('/devices/disconnect', {
      method: 'POST',
      body: { session_token: token, device_id: getDeviceId() },
    }).finally(() => API.clearTokens());
  }

  return { connect, reconnect, hasSession, heartbeat, disconnect, getDeviceId };
})();

if (typeof window !== 'undefined') window.DeviceAPI = DeviceAPI;
