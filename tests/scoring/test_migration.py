from app.core.database import fetch_one, execute


def test_new_columns_exist():
    cols = {r["name"] for r in _columns("challenges")}
    assert "ai_baseline" in cols
    cols = {r["name"] for r in _columns("submissions")}
    assert "scoring_version" in cols


def test_scoring_version_defaults_to_1():
    # Insert a minimal challenge + submission and confirm the default.
    execute(
        "INSERT INTO users (id, email, password_hash, name, user_type, email_verified) "
        "VALUES ('u1','d@d.com','x','Dev','developer',1)"
    )
    execute(
        "INSERT INTO challenges (id, created_by, title, slug, description, problem_statement_md, difficulty, category) "
        "VALUES ('c1','u1','T','t','d','p','easy','algo')"
    )
    execute(
        "INSERT INTO submissions (id, challenge_id, user_id) VALUES ('s1','c1','u1')"
    )
    row = fetch_one("SELECT scoring_version FROM submissions WHERE id='s1'")
    assert row["scoring_version"] == 1


def _columns(table: str):
    from app.core.database import fetch_all
    return fetch_all(f"PRAGMA table_info({table})")
