"""Smoke test: the demo runs end to end and prints each step."""

from optimizer.demo import main


def test_demo_runs_generate_callout_and_repair(capsys):
    main(["--staff", "25", "--seed", "42"])
    output = capsys.readouterr().out

    assert "1. Weekly schedule:" in output
    assert "2. Call-out:" in output
    assert "3. Repair:" in output
    assert "Independent validator: no rule violations." in output
