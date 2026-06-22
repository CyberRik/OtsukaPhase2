"""Account Intelligence — account-level (not deal-level) reasoning over a whole
customer relationship: health, trajectory, expansion, and a senior-manager read.
"""
from senpai.account.summary import build_account_summary, AccountSummary
from senpai.account.health import account_health, AccountHealth
from senpai.account.trajectory import relationship_trajectory, Pattern
from senpai.account.expansion import expansion_opportunities, Opportunity
from senpai.account.context import build_account_context, account_commentary_prompt

__all__ = [
    "build_account_summary", "AccountSummary",
    "account_health", "AccountHealth",
    "relationship_trajectory", "Pattern",
    "expansion_opportunities", "Opportunity",
    "build_account_context", "account_commentary_prompt",
]
