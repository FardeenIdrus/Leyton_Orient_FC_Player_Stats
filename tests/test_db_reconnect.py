"""Owner, 2026-11-10: after a database restart the web site kept failing (500, "server closed the
connection unexpectedly") until the web container itself was restarted -- its pooled connections
were dead. Every engine the site uses must test a pooled connection before handing it out
(pool_pre_ping), so a database restart heals on the next request."""


def test_web_login_engine_reconnects_after_a_database_restart():
    from lofc.web.app import DbUserStore
    assert DbUserStore().engine().pool._pre_ping is True


def test_data_engine_reconnects_after_a_database_restart():
    from lofc.dashboard import loaders
    assert loaders.get_engine().pool._pre_ping is True


def test_admin_engine_reconnects_after_a_database_restart():
    from lofc import admin
    assert admin._engine().pool._pre_ping is True


def test_engines_still_hide_parameters():
    from lofc.dashboard import loaders
    from lofc.web.app import DbUserStore
    assert loaders.get_engine().hide_parameters is True
    assert DbUserStore().engine().hide_parameters is True
