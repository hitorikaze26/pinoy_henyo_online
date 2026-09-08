'use strict';

/* ============================================================
   Team / Member API — /api/teams and /api/games/<id>/teams
   ============================================================ */

const TeamAPI = (() => {
  // POST /api/games/<game_id>/teams  { team_name, username }
  // Returns team_payload (includes leader member). Records the leader identity.
  async function createTeam(gameId, teamName, username) {
    const data = await API.request(`/games/${gameId}/teams`, {
      method: 'POST',
      body: { team_name: teamName, username },
      host: true,
    });
    API.setMemberIdentity(data.leader, {
      team_id: data.team_id,
      team_code: data.team_code,
      team_name: data.team_name,
    });
    if (data.team_id) API.setTeamId(data.team_id);
    if (data.team_code) API.setTeamCode(data.team_code);
    if (data.team_name) API.setTeamName(data.team_name);
    return data;
  }

  // POST /api/teams/<team_id>/members  { username }
  // Returns member_payload. The caller's identity is NOT changed: adding a
  // teammate never makes the calling device "become" the new member (which
  // would clobber a team leader's session into a plain team member).
  async function addMember(teamId, username) {
    return API.request(`/teams/${teamId}/members`, {
      method: 'POST',
      body: { username },
    });
  }

  // POST /api/games/<game_id>/join  { username, team_name | team_code }
  // Returns member_payload (joined an existing team) or team_payload (created one).
  async function joinGame(gameId, username, teamName, teamCode) {
    const body = { username };
    if (teamName) body.team_name = teamName;
    if (teamCode) body.team_code = teamCode;
    const data = await API.request(`/games/${gameId}/join`, {
      method: 'POST',
      body,
      host: true,
    });
    if (data.member_id) {
      API.setMemberIdentity(data);
    } else if (data.team_id) {
      API.setMemberIdentity(data.leader, data);
      API.setTeamId(data.team_id);
      API.setTeamCode(data.team_code);
      API.setTeamName(data.team_name);
    }
    return data;
  }

  // POST /api/teams/<team_id>/join  { username }
  // Returns member_payload. Records the member identity.
  async function joinTeam(teamId, username) {
    const data = await API.request(`/teams/${teamId}/join`, {
      method: 'POST',
      body: { username },
    });
    API.setMemberIdentity(data);
    return data;
  }

  // POST /api/teams/<team_id>/roles  { roles: [{ member_id, gameplay_role }] }
  function assignRoles(teamId, roles) {
    return API.request(`/teams/${teamId}/roles`, {
      method: 'POST',
      body: { roles },
      host: true,
    });
  }

  // Session (team-leader) variant of assignRoles for the player page.
  function assignMyTeamRoles(teamId, roles) {
    return API.request(`/teams/${teamId}/roles`, {
      method: 'POST',
      body: { roles },
      session: true,
    });
  }

  // GET /api/teams/<team_id>  (own-team roster via session, or host)
  // Returns the player's full team info + member roster (+ my_member_id).
  function getMyTeam(teamId) {
    return API.request(`/teams/${teamId}`, { session: true });
  }

  // PATCH /api/teams/<team_id>  { team_name }  (host or team-leader session)
  function updateTeamName(teamId, teamName) {
    return API.request(`/teams/${teamId}`, {
      method: 'PATCH',
      body: { team_name: teamName },
      host: true,
      session: true,
    });
  }

  // PATCH /api/members/<member_id>  { username }  (host or the member's own session)
  function updateUsername(memberId, username) {
    return API.request(`/members/${memberId}`, {
      method: 'PATCH',
      body: { username },
      host: true,
      session: true,
    });
  }

  // DELETE /api/teams/<team_id>  (host only)
  function deleteTeam(teamId) {
    return API.request(`/teams/${teamId}`, { method: 'DELETE', host: true });
  }

  // DELETE /api/members/<member_id>  (host or team leader)
  function removeMember(memberId) {
    return API.request(`/members/${memberId}`, {
      method: 'DELETE',
      host: true,
      session: true,
    });
  }

  // GET /api/teams/<team_id>/qr  (team-leader session or host token)
  function teamQr(teamId) {
    return API.request(`/teams/${teamId}/qr`, { host: true, session: true });
  }

  // POST /api/games/<game_id>/connection-request
  // Asks the host to approve this team. The team leader's session token is
  // sent in the header; when a raw connection token is available it is sent
  // in the body as well (the backend accepts either).
  function requestConnection(gameId, connectionToken) {
    const body = {};
    if (connectionToken) body.connection_token = connectionToken;
    return API.request(`/games/${gameId}/connection-request`, {
      method: 'POST',
      body,
      session: true,
    });
  }

  // POST /api/games/<game_id>/connection-requests/<team_id>/approve
  function approveConnection(gameId, teamId) {
    return API.request(`/games/${gameId}/connection-requests/${teamId}/approve`, {
      method: 'POST',
      host: true,
    });
  }

  // POST /api/games/<game_id>/connection-requests/<team_id>/decline
  function declineConnection(gameId, teamId) {
    return API.request(`/games/${gameId}/connection-requests/${teamId}/decline`, {
      method: 'POST',
      host: true,
    });
  }

  // POST /api/games/<game_id>/connection-requests/<team_id>/disconnect
  function disconnectConnection(gameId, teamId) {
    return API.request(`/games/${gameId}/connection-requests/${teamId}/disconnect`, {
      method: 'POST',
      host: true,
    });
  }

  // GET /api/games/<game_id>/teams
  // Returns the full live team roster ({ teams: [team_roster_payload] }).
  function listTeams(gameId) {
    return API.request(`/games/${gameId}/teams`, { host: true });
  }

  return {
    createTeam,
    addMember,
    joinGame,
    joinTeam,
    assignRoles,
    assignMyTeamRoles,
    getMyTeam,
    updateTeamName,
    updateUsername,
    deleteTeam,
    removeMember,
    teamQr,
    listTeams,
    requestConnection,
    approveConnection,
    declineConnection,
    disconnectConnection,
  };
})();

if (typeof window !== 'undefined') window.TeamAPI = TeamAPI;
