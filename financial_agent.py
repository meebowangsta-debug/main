#!/usr/bin/env python3
"""Daily financial analysis agent for frontier tech and strategic resources."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

TRACKED_TOPICS = [
    "AI software",
    "AI hardware",
    "AI infrastructure",
    "Space exploration",
    "Critical minerals",
    "Rare earth elements",
    "Robotics",
]

TOPIC_COMPANIES: dict[str, list[str]] = {
    "AI software": ["Microsoft", "Alphabet", "Meta", "Adobe", "Salesforce", "Palantir"],
    "AI hardware": ["NVIDIA", "AMD", "Intel", "TSMC", "ASML", "Samsung Electronics"],
    "AI infrastructure": ["Amazon", "Microsoft", "Alphabet", "Oracle", "Arista Networks", "Vertiv"],
    "Space exploration": ["Rocket Lab", "Boeing", "Northrop Grumman", "Lockheed Martin", "Maxar"],
    "Critical minerals": ["Rio Tinto", "BHP", "Glencore", "Freeport-McMoRan", "MP Materials"],
    "Rare earth elements": ["MP Materials", "Lynas Rare Earths", "China Northern Rare Earth Group"],
    "Robotics": ["ABB", "Fanuc", "Yaskawa", "Teradyne", "Rockwell Automation"],
}

DEFAULT_SOURCES = [
    "https://x.com/",
    "https://www.reuters.com/",
    "https://www.bloomberg.com/",
    "https://www.ft.com/",
    "https://www.wsj.com/",
    "https://www.cnbc.com/",
]

POSITIVE_CUES = {
    "beats",
    "beat",
    "surge",
    "growth",
    "contract win",
    "expands",
    "approved",
    "funding secured",
    "margin expansion",
    "record revenue",
}

NEGATIVE_CUES = {
    "miss",
    "delay",
    "lawsuit",
    "probe",
    "recall",
    "export ban",
    "downgrade",
    "cuts guidance",
    "cash burn",
    "dilution",
}

HIGH_SIGNAL_CUES = {
    "earnings",
    "guidance",
    "regulatory",
    "export control",
    "long-term contract",
    "production ramp",
    "capex",
    "supply agreement",
    "government award",
}


@dataclass
class Observation:
    topic: str
    company: str
    source: str
    url: str
    summary: str


@dataclass
class Assessment:
    observation: Observation
    impact: str
    signal_score: int
    reason: str


def normalize(text: str) -> str:
    return text.strip().lower()


def classify_impact(summary: str) -> tuple[str, str]:
    text = normalize(summary)
    pos_hits = [cue for cue in POSITIVE_CUES if cue in text]
    neg_hits = [cue for cue in NEGATIVE_CUES if cue in text]

    if len(pos_hits) > len(neg_hits):
        return "positive", f"positive cues: {', '.join(pos_hits)}"
    if len(neg_hits) > len(pos_hits):
        return "negative", f"negative cues: {', '.join(neg_hits)}"
    return "mixed/unclear", "insufficient directional evidence"


def signal_score(summary: str, source: str) -> tuple[int, str]:
    text = normalize(summary)
    score = 0
    reasons: list[str] = []

    cue_hits = [cue for cue in HIGH_SIGNAL_CUES if cue in text]
    if cue_hits:
        score += min(3, len(cue_hits))
        reasons.append(f"hard catalysts: {', '.join(cue_hits)}")

    source_l = normalize(source)
    if "x.com" in source_l:
        score += 1
        reasons.append("fast signal source (x.com)")
    elif any(domain in source_l for domain in ("reuters", "bloomberg", "ft.com", "wsj", "cnbc")):
        score += 2
        reasons.append("high-credibility financial source")

    return score, "; ".join(reasons) if reasons else "limited specificity"


def assess(observations: Iterable[Observation]) -> list[Assessment]:
    assessed: list[Assessment] = []
    for obs in observations:
        impact, impact_reason = classify_impact(obs.summary)
        score, signal_reason = signal_score(obs.summary, obs.source)
        reason = f"{impact_reason}; {signal_reason}"
        assessed.append(Assessment(observation=obs, impact=impact, signal_score=score, reason=reason))

    return sorted(assessed, key=lambda a: (a.signal_score, a.impact != "mixed/unclear"), reverse=True)


def render_report(assessments: list[Assessment]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"Daily Frontier Research Brief ({now})",
        "",
        "Principles: skeptical, concise, capital-scarce, opportunity-cost aware.",
        "",
    ]

    if not assessments:
        lines.append("No observations supplied.")
        return "\n".join(lines)

    for idx, item in enumerate(assessments, start=1):
        obs = item.observation
        lines.extend(
            [
                f"{idx}. [{obs.topic}] {obs.company} -> {item.impact.upper()} (signal {item.signal_score}/5)",
                f"   Why: {item.reason}.",
                f"   Source: {obs.source} ({obs.url})",
            ]
        )

    lines.extend(
        [
            "",
            "Action filter:",
            "- Focus only on items with signal >=3 and clear positive/negative direction.",
            "- Ignore narrative-only items without earnings, regulation, supply, or contract implications.",
        ]
    )
    return "\n".join(lines)


def load_observations(path: Path) -> list[Observation]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [Observation(**row) for row in payload]


def print_bootstrap_guide() -> None:
    print("Financial Analysis AI Agent - Daily Bootstrap")
    print("")
    print("Tracked topics:")
    for topic in TRACKED_TOPICS:
        print(f"- {topic}")

    print("\nPriority source set:")
    for src in DEFAULT_SOURCES:
        print(f"- {src}")

    print("\nMajor companies to monitor:")
    for topic, companies in TOPIC_COMPANIES.items():
        print(f"- {topic}: {', '.join(companies)}")

    print("\nWorkflow:")
    print("1) Collect 3-8 high-signal observations per topic from x.com + financial press.")
    print("2) Reject rumor-only claims without filings, contracts, guidance, or regulator actions.")
    print("3) Classify impact: positive / negative / mixed.")
    print("4) Rank by signal strength and opportunity cost.")
    print("5) Produce a short watchlist and what to ignore.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Financial analysis AI agent helper")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("bootstrap", help="Print research scope, sources, and workflow")

    analyze_parser = sub.add_parser("analyze", help="Analyze a JSON list of observations")
    analyze_parser.add_argument("--input", required=True, help="Path to observations JSON")

    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "bootstrap":
        print_bootstrap_guide()
        return

    observations = load_observations(Path(args.input))
    report = render_report(assess(observations))
    print(report)


if __name__ == "__main__":
    main()
