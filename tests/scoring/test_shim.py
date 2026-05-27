def test_shim_reexports_engine_score_submission():
    from app.services.challenge_scoring import score_submission as shim_fn
    from app.services.scoring.engine import score_submission as real_fn
    assert shim_fn is real_fn
