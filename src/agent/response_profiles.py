from __future__ import annotations

from dataclasses import dataclass

from src.agent.profiles import ResponseProfile, coerce_response_profile


@dataclass(frozen=True)
class ResponseDisplayPolicy:
    show_metadata: bool
    show_sql_inline: bool
    technical_details_expanded: bool
    show_reporting_audit: bool
    show_technical_debug: bool
    summary_heading: str
    answer_heading: str


RESPONSE_DISPLAY_POLICIES: dict[ResponseProfile, ResponseDisplayPolicy] = {
    ResponseProfile.MANAGEMENT: ResponseDisplayPolicy(
        show_metadata=False,
        show_sql_inline=False,
        technical_details_expanded=False,
        show_reporting_audit=False,
        show_technical_debug=False,
        summary_heading="Business Summary",
        answer_heading="Direct Answer",
    ),
    ResponseProfile.ANALYST: ResponseDisplayPolicy(
        show_metadata=True,
        show_sql_inline=True,
        technical_details_expanded=False,
        show_reporting_audit=False,
        show_technical_debug=False,
        summary_heading="Analytical Summary",
        answer_heading="Answer",
    ),
    ResponseProfile.TECHNICAL: ResponseDisplayPolicy(
        show_metadata=True,
        show_sql_inline=True,
        technical_details_expanded=False,
        show_reporting_audit=True,
        show_technical_debug=True,
        summary_heading="Analytical Summary",
        answer_heading="Answer",
    ),
}


def display_policy_for_response_profile(
    response_profile: ResponseProfile | str,
) -> ResponseDisplayPolicy:
    return RESPONSE_DISPLAY_POLICIES[coerce_response_profile(response_profile)]
