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
  // Returns member_payload. Records the (new or existing) member identity.
  async function addMember(teamId, username) {
    const data = await API.request(`/teams/${teamId}/members`, {
      method: 'POST',
      body: { username },
    });
    API.setMemberIdentity(data);
    return data;
  }

  // POST /api/games/<game_id>/join  { username, team_name | team_code }
  // Returns member_payload (joined an existing team) or team_payload (created one).
  async function joinGame(gameId, username, teamName, teamCode) {
    const body = { username };
    if (teamName) body.team_name = teamName;
    if (teamCode) body.team_code = teamCode;
    const data = await API.request(`/games/${gameId}/join`, { method: 'POST', body });
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

  // PATCH /api/teams/<team_id>  { team_name }  (team-leader session or host)
  function updateTeamName(teamId, teamName) {
    return API.request(`/teams/${teamId}`, {
      method: 'PATCH',
      body: { team_name: teamName },
      session: true,
    });
  }

  // PATCH /api/members/<member_id>  { username }  (own session or host)
  function updateUsername(memberId, username) {
    return API.request(`/members/${memberId}`, {
      method: 'PATCH',
      body: { username },
      session: true,
    });
  }

  // GET /api/teams/<team_id>/qr
  function teamQr(teamId) {
    return API.request(`/teams/${teamId}/qr`, { host: true });
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
    teamQr,
    listTeams,
  };
})();

if (typeof window !== 'undefined') window.TeamAPI = TeamAPI;
