from ai_curate.job_validation import validate_ai_curate_request


def _validate(data, *, batches=None, default_model="vl-scorer", allowed_models=None):
    return validate_ai_curate_request(
        data,
        get_batches=lambda: batches or ["alpha"],
        default_model=default_model,
        default_top_n=15,
        top_n_cap=100,
        element_cap=12,
        allowed_source_folders={"inbox", "shortlisted"},
        allowed_dest_folders={"shortlisted", "finals", "rejects"},
        allowed_models=allowed_models,
    )


def test_missing_batch_rejected():
    params, err = _validate({})

    assert params is None
    assert err == ({"error": "batch is required"}, 400)


def test_non_string_scalar_fields_are_rejected():
    for field, value in (
        ("batch", 7),
        ("prompt", []),
        ("source_folder", {}),
        ("destination_folder", 7),
        ("model", []),
    ):
        data = {"batch": "alpha", "elements": ["x"], "model": "vl-scorer"}
        data[field] = value
        params, err = _validate(data)

        assert params is None
        assert err is not None
        assert err[1] == 400


def test_nonexistent_batch_rejected():
    params, err = _validate({"batch": "missing", "elements": ["x"]})

    assert params is None
    assert err[1] == 400
    assert "does not exist" in err[0]["error"]


def test_missing_elements_rejected():
    params, err = _validate({"batch": "alpha"})

    assert params is None
    assert "elements is required" in err[0]["error"]


def test_elements_must_be_list():
    params, err = _validate({"batch": "alpha", "elements": "not-list"})

    assert params is None
    assert "elements" in err[0]["error"]


def test_element_cap_rejected():
    params, err = _validate({"batch": "alpha", "elements": [str(i) for i in range(13)]})

    assert params is None
    assert err == ({"error": "too many elements (max 12)"}, 400)


def test_blank_elements_rejected_after_stripping():
    params, err = _validate({"batch": "alpha", "elements": [" ", ""]})

    assert params is None
    assert "elements must contain" in err[0]["error"]


def test_invalid_source_folder_rejected():
    params, err = _validate({"batch": "alpha", "elements": ["x"], "source_folder": "bad"})

    assert params is None
    assert "source_folder" in err[0]["error"]


def test_quality_flags_must_be_list_when_present():
    params, err = _validate({"batch": "alpha", "elements": ["x"], "quality_flags": "bad"})

    assert params is None
    assert err == ({"error": "quality_flags must be a list of strings"}, 400)


def test_top_n_must_be_integer():
    params, err = _validate({"batch": "alpha", "elements": ["x"], "top_n": "abc"})

    assert params is None
    assert err == ({"error": "top_n must be an integer"}, 400)


def test_top_n_range_rejected():
    params, err = _validate({"batch": "alpha", "elements": ["x"], "top_n": 101})

    assert params is None
    assert err == ({"error": "top_n must be between 1 and 100"}, 400)


def test_move_requires_valid_destination():
    params, err = _validate({"batch": "alpha", "elements": ["x"], "move_enabled": True})

    assert params is None
    assert "destination_folder is required" in err[0]["error"]


def test_missing_model_rejected():
    params, err = _validate({"batch": "alpha", "elements": ["x"]}, default_model="")

    assert params is None
    assert "model is required" in err[0]["error"]


def test_valid_minimal_request_applies_defaults():
    params, err = _validate({"batch": "alpha", "elements": [" x "], "model": "vl-scorer"})

    assert err is None
    assert params == {
        "batch": "alpha",
        "prompt": "",
        "source_folder": "inbox",
        "elements": ["x"],
        "quality_flags": None,
        "top_n": 15,
        "move_enabled": False,
        "destination_folder": None,
        "model": "vl-scorer",
    }


def test_valid_full_request():
    params, err = _validate(
        {
            "batch": "alpha",
            "prompt": " prompt ",
            "source_folder": "shortlisted",
            "elements": ["sharp", "light"],
            "quality_flags": ["anatomy"],
            "top_n": "5",
            "move_enabled": True,
            "destination_folder": "finals",
            "model": "custom-model",
        },
        allowed_models=["custom-model", "vl-scorer"],
    )

    assert err is None
    assert params["prompt"] == "prompt"
    assert params["source_folder"] == "shortlisted"
    assert params["quality_flags"] == ["anatomy"]
    assert params["top_n"] == 5
    assert params["move_enabled"] is True
    assert params["destination_folder"] == "finals"
    assert params["model"] == "custom-model"


def test_model_not_in_allowed_list_rejected():
    """Submission with a model not in the allowed list must be rejected."""
    params, err = _validate(
        {"batch": "alpha", "elements": ["x"], "model": "unknown-model"},
        allowed_models=["vl-scorer"],
    )

    assert params is None
    assert err is not None
    assert err[1] == 400
    assert "model" in err[0]["error"].lower()


def test_empty_allowed_models_rejects_any_model():
    """When no models are configured, any model submission must be rejected."""
    params, err = _validate(
        {"batch": "alpha", "elements": ["x"], "model": "any-model"},
        allowed_models=[],
    )

    assert params is None
    assert err is not None
    assert err[1] == 400
    assert "model" in err[0]["error"].lower()


def test_default_model_must_be_in_allowed_list():
    """Default model is accepted only when in the allowed list."""
    params, err = _validate(
        {"batch": "alpha", "elements": ["x"]},  # no model supplied, uses default
        default_model="vl-scorer",
        allowed_models=["vl-scorer"],
    )

    assert err is None
    assert params["model"] == "vl-scorer"


def test_default_model_rejected_when_not_in_allowed_list():
    """Default model is rejected when it is not in the allowed models list."""
    params, err = _validate(
        {"batch": "alpha", "elements": ["x"]},  # no model supplied, uses default
        default_model="old-model",
        allowed_models=["new-model"],
    )

    assert params is None
    assert err is not None
    assert err[1] == 400
    assert "model" in err[0]["error"].lower()


def test_allowed_models_none_skips_check_backward_compat():
    """When allowed_models is None (caller didn't specify), any valid model string passes."""
    params, err = _validate(
        {"batch": "alpha", "elements": ["x"], "model": "anything"},
        allowed_models=None,
    )

    assert err is None
    assert params["model"] == "anything"
