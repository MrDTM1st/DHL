"""The Haulier Rejection Form worked by name (work_pc/ctms_form.py, 11/11): what gets filled in is worked out from the
page as UI Automation reads it - a question by its words, a choice by its exact words - and nothing is touched unless
every answer has its place. Made-up answers only.

    python -m pytest tests/test_ctms_form.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "work_pc"))
import ctms_form as F  # noqa: E402


def _page(**state):
    """A page shaped the way the form reads (live 11/11 on a copy of it): groups holding their choices, text boxes
    named by their question, an Other box inside its group, Submit at the end."""
    on = state.get
    return [
        {"k": "text", "nm": "Haulier Rejection Form 2026", "d": 1},
        {"k": "group", "nm": "Questions", "d": 1},                                      # a section round them all
        {"k": "group", "nm": "1. Haulier Name *", "d": 2},
        {"k": "text", "nm": "1. Haulier Name *", "d": 3},
        {"k": "checkbox", "nm": "DE O'Reilly", "d": 3, "on": bool(on("deo"))},
        {"k": "checkbox", "nm": "DHL NOC", "d": 3, "on": bool(on("noc"))},
        {"k": "edit", "nm": "2. Date of Job *", "d": 2, "v": on("date") or ""},
        {"k": "group", "nm": "5. Consolidated Delivery - Yes/No *", "d": 2},
        {"k": "radio", "nm": "Yes", "d": 3, "on": False},
        {"k": "radio", "nm": "No", "d": 3, "on": bool(on("no"))},
        {"k": "group", "nm": "9. Rear-Steer *", "d": 2},
        {"k": "radio", "nm": "Yes", "d": 3, "on": False},
        {"k": "radio", "nm": "No", "d": 3, "on": False},
        {"k": "group", "nm": "10. Rejection Reason *", "d": 2},
        {"k": "radio", "nm": "No Reply", "d": 3, "on": False},
        {"k": "radio", "nm": "Other", "d": 3, "on": bool(on("other"))},
        {"k": "edit", "nm": "Other answer", "d": 3, "v": on("why") or ""},
        {"k": "edit", "nm": "Password", "d": 2, "password": True},
        {"k": "button", "nm": "Submit", "d": 1},
    ]


ANSWERS = [{"q": "Haulier Name", "tick": ["DHL NOC"]}, {"q": "Date of Job", "text": "11/16/2026"},
           {"q": "Consolidated Delivery", "pick": "No"}, {"q": "Rejection Reason", "pick": "Other", "other": "no HIAB"}]


def test_each_answer_is_found_by_its_question_s_words_and_its_choice_s_exact_words():
    steps = F.plan(_page(), ANSWERS)
    page = _page()
    assert [(how, page[i]["nm"], value) for how, i, value in steps] == [
        ("tick", "DHL NOC", "DHL NOC"), ("text", "2. Date of Job *", "11/16/2026"), ("pick", "No", "No"),
        ("pick", "Other", "Other"), ("text", "Other answer", "no HIAB")]
    # Consolidated's No, not Rear-Steer's: the question's own group, not the section round it
    assert steps[2][1] == 9


def test_anything_not_on_the_page_stops_it_before_a_thing_is_touched_and_says_what():
    try:
        F.plan(_page(), [{"q": "Haulier Name", "tick": ["DHL NOC", "Nobody Ltd"]}, {"q": "Trailer Colour", "pick": "Red"},
                         {"q": "Quantity", "text": "15"}])
        raise AssertionError("should have refused")
    except ValueError as e:
        said = str(e)
    assert "nothing was filled in" in said
    assert "Haulier Name: Nobody Ltd" in said and "Trailer Colour: the question" in said and "Quantity: its box" in said


def test_a_password_box_is_never_one_to_type_into():
    try:
        F.plan(_page(), [{"q": "Password", "text": "x"}])
        raise AssertionError("should have refused")
    except ValueError as e:
        assert "Password: its box" in str(e)


def test_what_doesnt_read_back_is_named_and_a_full_read_back_is_clean():
    steps = F.plan(_page(), ANSWERS)
    assert F.check(_page(noc=True, date="11/16/2026", no=True, other=True, why="no HIAB"), steps) == []
    off = F.check(_page(noc=False, date="16/11/2026", no=True, other=True, why="no HIAB"), steps)
    assert off == ["DHL NOC isn't ticked", "'2. Date of Job *' reads '16/11/2026', not '11/16/2026'"]


def test_only_a_page_that_has_taken_the_response_counts_as_submitted():
    assert F.confirmed(_page()) == ""                                                   # Submit still there
    done = [{"k": "text", "nm": "Haulier Rejection Form 2026", "d": 1},
            {"k": "text", "nm": "Your response was submitted.", "d": 1}]
    assert "Your response was submitted." in F.confirmed(done)
    assert F.confirmed([{"k": "text", "nm": "Haulier Rejection Form 2026", "d": 1}]) == ""   # gone, but no word of it


def _real(**on):
    """The form as the work PC's Edge reads it (11/11): each question a group named with its number and 'Required
    to answer ... Single choice.', each choice beside a group of its own words, the date a combo box, Other a choice
    called 'Other answer' with a box of its own."""
    return [
        {"k": "group", "nm": "Haulier Rejection Form 2026", "d": 1},
        {"k": "text", "nm": "1. Haulier Name Required to answer", "d": 2},
        {"k": "group", "nm": "1. Haulier Name Required to answer Multiple choice. ", "d": 2},
        {"k": "checkbox", "nm": "DE O'Reilly", "d": 3, "on": False},
        {"k": "group", "nm": "DE O'Reilly", "d": 3},
        {"k": "text", "nm": "DE O'Reilly", "d": 4},
        {"k": "checkbox", "nm": "DHL NOC", "d": 3, "on": bool(on.get("noc"))},
        {"k": "group", "nm": "DHL NOC", "d": 3},
        {"k": "text", "nm": "DHL NOC", "d": 4},
        {"k": "combo", "nm": "2. Date of Job Required to answer Date. ", "d": 2, "v": on.get("date", "")},
        {"k": "edit", "nm": "3. Collection Site Single line text. ", "d": 2, "v": ""},
        {"k": "group", "nm": "8. Vehicle Type Required to answer Single choice. ", "d": 2},
        {"k": "radio", "nm": "Artic Hiab", "d": 3, "on": False},
        {"k": "group", "nm": "Artic Hiab", "d": 3},
        {"k": "text", "nm": "Artic Hiab", "d": 4},
        {"k": "radio", "nm": "Other answer", "d": 3, "on": False},
        {"k": "edit", "nm": "Other answer", "d": 3, "v": ""},
        {"k": "group", "nm": "10. Rejection Reason Required to answer Single choice. ", "d": 2},
        {"k": "radio", "nm": "No Availability - Vehicle Type", "d": 3, "on": False},
        {"k": "group", "nm": "No Availability - Vehicle Type", "d": 3},
        {"k": "text", "nm": "No Availability - Vehicle Type", "d": 4},
        {"k": "radio", "nm": "Other answer", "d": 3, "on": False},
        {"k": "edit", "nm": "Other answer", "d": 3, "v": ""},
        {"k": "button", "nm": "Submit", "d": 2},
    ]


def test_the_real_form_s_names_a_date_combo_and_other_answer():
    page = _real()
    steps = F.plan(page, [{"q": "Haulier Name", "tick": ["DHL NOC"]}, {"q": "Date of Job", "text": "11/16/2026"},
                          {"q": "Vehicle Type", "pick": "Artic Hiab"},
                          {"q": "Rejection Reason", "pick": "Other", "other": "no HIAB"}])
    assert [(how, i) for how, i, _ in steps] == [("tick", 6), ("text", 9), ("pick", 12), ("pick", 21), ("text", 22)]
    # Vehicle Type is question 8 - not the Rejection Reason that shares its words
    assert F.plan(page, [{"q": "Vehicle Type", "pick": "Other", "other": "Low loader"}]) == [
        ("pick", 15, "Other"), ("text", 16, "Low loader")]
    try:
        F.plan(page, [{"q": "Vehicle Type", "pick": "No Availability - Vehicle Type"}])
        raise AssertionError("a Rejection Reason is no Vehicle Type")
    except ValueError as e:
        assert "Vehicle Type: No Availability - Vehicle Type" in str(e)


def test_the_form_is_known_by_its_name_alone():
    assert F.is_form("Haulier Rejection Form 2026") and F.is_form("Haulier Rejection Form 2026 - Work - Microsoft Edge")
    assert not F.is_form("DigiHaul Job Tracker.xlsx") and not F.is_form("")
