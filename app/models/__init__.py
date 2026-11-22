"""Importing this package registers every model on Base.metadata, which is
what Alembic's autogenerate compares the live database against."""
from app.models.imports import Import, ImportDocument
from app.models.public import Environment, Invitation, Notification, Profile, Project, ProjectMember
from app.models.requirements import AcceptanceCriterion, Requirement
from app.models.runs import Action, AnalysisRun, Evidence, Result
from app.models.usage import AIUsage

__all__ = [
    "AIUsage",
    "AcceptanceCriterion",
    "Action",
    "AnalysisRun",
    "Environment",
    "Evidence",
    "Import",
    "ImportDocument",
    "Invitation",
    "Notification",
    "Profile",
    "Project",
    "ProjectMember",
    "Requirement",
    "Result",
]

from app.models.integration import Dispatch, Callback, ResultDetail

from app.models.assets import ImportRequirement, EnvironmentVerification
