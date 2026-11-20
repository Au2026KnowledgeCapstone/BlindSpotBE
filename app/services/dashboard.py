"""Project-level aggregates, counted in the database.

Every figure here is derivable from the per-run endpoints, which is exactly
the problem: doing it that way costs the caller one results request per run,
so a project with a few hundred runs opens its dashboard with a few hundred
concurrent reads. These are two grouped queries instead.
"""
from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import distinct_on

from app.models import AnalysisRun, Requirement, Result
from app.services.resources import uid


def _latest_verdict_per_requirement(project_id):
    """One row per requirement: the verdict from its most recently completed
    run. The ordering matches resources.requirement_out exactly, so a
    requirement's reported `latest_result` can never disagree with the
    coverage counts below."""
    return (
        select(Result.requirement_id, Result.verdict.label("verdict"))
        .join(AnalysisRun, AnalysisRun.id == Result.analysis_run_id)
        .where(Result.project_id == project_id, AnalysisRun.completed_at.is_not(None))
        .order_by(Result.requirement_id, AnalysisRun.completed_at.desc(), AnalysisRun.id.desc())
        .ext(distinct_on(Result.requirement_id))
        .subquery()
    )


def _outcome_per_run(project_id):
    """One row per completed run that produced results, labelled with the
    outcome a reviewer would read off it. `status` rather than `completed_at`
    because that is the run state the product shows."""
    return (
        select(
            case(
                (func.bool_or(Result.verdict == "fail"), "fail"),
                (func.bool_or(Result.verdict == "inconclusive"), "inconclusive"),
                else_="pass",
            ).label("outcome")
        )
        .select_from(AnalysisRun)
        .join(Result, Result.analysis_run_id == AnalysisRun.id)
        .where(AnalysisRun.project_id == project_id, AnalysisRun.status == "completed")
        .group_by(AnalysisRun.id)
        .subquery()
    )


def project_dashboard(db, context):
    project_id = uid(context.project_id)
    total, approved = db.execute(
        select(
            func.count(Requirement.id),
            func.count(Requirement.id).filter(Requirement.approval_status == "approved"),
        ).where(Requirement.project_id == project_id)
    ).one()

    latest = _latest_verdict_per_requirement(project_id)
    verdicts = dict(db.execute(select(latest.c.verdict, func.count()).group_by(latest.c.verdict)).all())
    tested = sum(verdicts.values())
    passed, failed = verdicts.get("pass", 0), verdicts.get("fail", 0)

    runs = _outcome_per_run(project_id)
    outcomes = dict(db.execute(select(runs.c.outcome, func.count()).group_by(runs.c.outcome)).all())

    return {
        "requirements": {
            "total_requirements": total,
            "approved_requirements": approved,
            "requirements_tested": tested,
            "requirements_passed": passed,
            "requirements_failed": failed,
            # Derived, per the schema: anything tested that neither passed nor failed.
            "requirements_inconclusive": tested - passed - failed,
            "requirements_untested": total - tested,
        },
        "runs": {
            "total_runs": sum(outcomes.values()),
            "runs_passed": outcomes.get("pass", 0),
            "runs_failed": outcomes.get("fail", 0),
            "runs_inconclusive": outcomes.get("inconclusive", 0),
        },
    }
