import secrets

GAME_CODE_PREFIX = "PH"
GAME_CODE_LENGTH = 4

TEAM_CODE_LENGTH = 4

GAME_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def generate_game_code():
    suffix = "".join(
        secrets.choice(GAME_CODE_ALPHABET) for _ in range(GAME_CODE_LENGTH)
    )
    return "{}{}".format(GAME_CODE_PREFIX, suffix)


def generate_team_code():
    return "".join(
        secrets.choice(GAME_CODE_ALPHABET) for _ in range(TEAM_CODE_LENGTH)
    )