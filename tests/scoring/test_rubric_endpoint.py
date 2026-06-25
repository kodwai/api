from app.core.database import execute


def _public_challenge():
    execute("INSERT INTO users (id, email, password_hash, name, user_type, email_verified) "
            "VALUES ('u1','a@a.com','x','A','company',1)")
    execute("INSERT INTO challenges (id, created_by, title, slug, description, problem_statement_md, "
            "difficulty, category, scoring_config, is_public) "
            "VALUES ('c1','u1','T','t','d','p','easy','algo','{}',1)")


def test_rubric_default_profile(client):
    _public_challenge()
    resp = client.get("/api/challenges/c1/rubric")
    assert resp.status_code == 200
    data = resp.json()
    assert data["profile"] == "balanced"
    names = {a["name"] for a in data["axes"]}
    assert names == {"direction", "outcome", "lift"}
    direction = next(a for a in data["axes"] if a["name"] == "direction")
    assert direction["points"] == 50
    # zero-weight baseline_lift is hidden
    lift = next(a for a in data["axes"] if a["name"] == "lift")
    assert all(s["name"] != "baseline_lift" for s in lift["signals"])
    # signals carry human-readable labels
    assert any(s["label"] == "Spec Precision" for s in direction["signals"])


def test_rubric_by_slug(client):
    _public_challenge()
    assert client.get("/api/challenges/t/rubric").status_code == 200


def test_rubric_404(client):
    assert client.get("/api/challenges/nope/rubric").status_code == 404
