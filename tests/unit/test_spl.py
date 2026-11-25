from logops.spl import analyze, split_pipeline

# The three rules shipped with v1. They are kept as regression cases.
FAILED_LOGIN = (
    "index=main sourcetype=security_logs action=failed_login | stats count by src_ip | where count > 3"
)
DB_TIMEOUT = "index=main sourcetype=db_logs error=timeout | stats count by host | where count > 0"
PHANTOM_SCAN = (
    "index=ghost_network_logs sourcetype=firewall_events | stats count by dest_port | where count > 10"
)


def test_failed_login_rule() -> None:
    a = analyze(FAILED_LOGIN)
    assert a.indexes == ("main",)
    assert a.sourcetypes == ("security_logs",)
    assert a.filter_fields == ("action",)
    assert a.group_by_fields == ("src_ip",)
    assert "count" in a.derived_fields
    assert a.commands == ("stats", "where")
    assert len(a.thresholds) == 1
    assert (a.thresholds[0].field, a.thresholds[0].op, a.thresholds[0].value) == ("count", ">", 3.0)
    assert a.required_event_fields == ("action", "src_ip")
    assert a.unparsed == ()


def test_host_is_metadata_not_required_field() -> None:
    a = analyze(DB_TIMEOUT)
    assert a.required_event_fields == ("error",)
    assert a.group_by_fields == ("host",)


def test_phantom_index() -> None:
    a = analyze(PHANTOM_SCAN)
    assert a.indexes == ("ghost_network_logs",)
    assert a.sourcetypes == ("firewall_events",)
    assert a.required_event_fields == ("dest_port",)
    assert a.thresholds[0].value == 10.0


def test_pipe_inside_quotes_is_not_a_command_boundary() -> None:
    segments, has_sub = split_pipeline('index=web uri="/a|b" | stats count')
    assert segments == ['index=web uri="/a|b"', "stats count"]
    assert not has_sub


def test_quoted_values_and_not_operator() -> None:
    a = analyze('index=web sourcetype="access combined" NOT status=200 user!="svc account"')
    assert a.sourcetypes == ("access combined",)
    assert set(a.filter_fields) == {"status", "user"}


def test_multiple_indexes_and_or() -> None:
    a = analyze("(index=a OR index=b) sourcetype=x | stats dc(user) as users by src_ip")
    assert a.indexes == ("a", "b")
    assert a.aggregate_fields == ("user",)
    assert "users" in a.derived_fields
    assert set(a.required_event_fields) == {"user", "src_ip"}


def test_eval_and_rename_create_derived_fields() -> None:
    a = analyze(
        "index=a | eval risk=score*2 | rename src as source_ip | where risk > 5 | stats count by source_ip"
    )
    assert "risk" in a.derived_fields
    assert "source_ip" in a.derived_fields
    assert "src" in a.required_event_fields
    assert "risk" not in a.required_event_fields
    assert "source_ip" not in a.required_event_fields


def test_fields_after_transform_are_not_raw_dependencies() -> None:
    a = analyze("index=a sourcetype=b | stats count by host | search count>5")
    assert a.required_event_fields == ()
    assert a.thresholds[0].field == "count"


def test_tstats_generating_command() -> None:
    a = analyze(
        "| tstats count latest(_time) as last where index=main sourcetype=security_logs by sourcetype"
    )
    assert a.indexes == ("main",)
    assert a.sourcetypes == ("security_logs",)
    assert a.commands[0] == "tstats"


def test_unknown_constructs_are_reported_not_guessed() -> None:
    a = analyze("index=a `my_macro` [search index=b | fields user] | lookup assets ip | frobnicate x")
    assert "macro" in a.unparsed
    assert "subsearch" in a.unparsed
    assert "command:lookup" in a.unparsed
    assert "command:frobnicate" in a.unparsed
    assert a.indexes == ("a",)


def test_where_with_function_and_string() -> None:
    a = analyze('index=a | where like(user, "adm%") AND attempts >= 3')
    assert "user" in a.filter_fields
    assert "attempts" in a.filter_fields
    assert "like" not in a.filter_fields
    assert a.thresholds[0].op == ">="


def test_empty_and_garbage_input_do_not_raise() -> None:
    assert analyze("").indexes == ()
    analyze("|||")
    analyze('index="unterminated')
