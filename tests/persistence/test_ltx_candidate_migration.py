from server.persistence.postgres.schema import render_migrations


def test_ltx_candidate_source_migration_extends_the_existing_constraint() -> None:
    migration = next(
        sql
        for sql in render_migrations("voiceagent_test")
        if "motion_base_candidates_source_kind_check" in sql
    )

    assert 'ALTER TABLE "voiceagent_test".motion_base_candidates' in migration
    assert "'ltx'" in migration


def test_minimax_candidate_source_migration_preserves_all_provider_sources() -> None:
    migration = next(
        sql
        for sql in render_migrations("voiceagent_test")
        if "motion_base_candidates_source_kind_check" in sql and "'minimax'" in sql
    )

    assert "'upload'" in migration
    assert "'vidu'" in migration
    assert "'liveportrait'" in migration
    assert "'ltx'" in migration
    assert "'minimax'" in migration


def test_replayed_provider_constraint_migrations_remain_forward_compatible() -> None:
    migrations = [
        sql
        for sql in render_migrations("voiceagent_test")
        if "motion_base_candidates_source_kind_check" in sql
    ]

    assert migrations
    assert all("'minimax'" in migration for migration in migrations)
