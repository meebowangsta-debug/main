from financial_agent import Observation, assess, render_report


def test_assess_ranks_high_signal_and_negative() -> None:
    observations = [
        Observation(
            topic="AI hardware",
            company="NVIDIA",
            source="Reuters",
            url="https://www.reuters.com/example",
            summary="NVIDIA beats earnings and raises guidance after long-term contract win.",
        ),
        Observation(
            topic="Space exploration",
            company="Rocket Lab",
            source="x.com",
            url="https://x.com/example",
            summary="Rocket Lab delay reported for next launch window.",
        ),
    ]

    assessments = assess(observations)

    assert assessments[0].observation.company == "NVIDIA"
    assert assessments[0].impact == "positive"
    assert assessments[1].impact == "negative"


def test_render_report_contains_action_filter() -> None:
    observations = [
        Observation(
            topic="Robotics",
            company="ABB",
            source="Bloomberg",
            url="https://www.bloomberg.com/example",
            summary="ABB expands robotics production ramp with government award.",
        )
    ]

    report = render_report(assess(observations))

    assert "Action filter:" in report
    assert "ABB" in report
