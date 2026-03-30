from __future__ import annotations

import json
import secrets

from fastapi import APIRouter, HTTPException, status

from app.core.database import execute, fetch_all, fetch_one
from app.core.deps import CurrentUser
from app.schemas.project import ProjectCreate, ProjectResponse, ProjectUpdate

router = APIRouter(prefix="/projects", tags=["projects"])


def _row_to_response(row: dict) -> ProjectResponse:
    """Convert a database row to a ProjectResponse, deserializing JSON fields."""
    data = dict(row)
    data["rubric"] = json.loads(data["rubric"]) if data.get("rubric") else []
    data["allowed_tools"] = json.loads(data["allowed_tools"]) if data.get("allowed_tools") else None
    data["disallowed_tools"] = json.loads(data["disallowed_tools"]) if data.get("disallowed_tools") else None
    data["is_archived"] = bool(data.get("is_archived", 0))
    return ProjectResponse(**data)


def _get_project_or_404(project_id: str, org_id: str) -> dict:
    """Fetch a project and verify it belongs to the organization."""
    project = fetch_one(
        """SELECT id, organization_id, title, description, problem_statement_md,
                  time_limit_minutes, difficulty, allowed_tools, disallowed_tools,
                  rubric, max_budget_usd, is_archived, created_at, updated_at
           FROM projects WHERE id = ? AND organization_id = ?""",
        (project_id, org_id),
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.get("", response_model=list[ProjectResponse])
def list_projects(
    current_user: CurrentUser,
    is_archived: bool = False,
) -> list[ProjectResponse]:
    """List projects for the current user's organization."""
    rows = fetch_all(
        """SELECT id, organization_id, title, description, problem_statement_md,
                  time_limit_minutes, difficulty, allowed_tools, disallowed_tools,
                  rubric, max_budget_usd, is_archived, created_at, updated_at
           FROM projects
           WHERE organization_id = ? AND is_archived = ?
           ORDER BY created_at DESC""",
        (current_user["organization_id"], int(is_archived)),
    )
    return [_row_to_response(row) for row in rows]


@router.post("", response_model=ProjectResponse, status_code=201)
def create_project(body: ProjectCreate, current_user: CurrentUser) -> ProjectResponse:
    """Create a new project."""
    project_id = secrets.token_hex(16)
    org_id = current_user["organization_id"]

    rubric_json = json.dumps([dim.model_dump() for dim in body.rubric])
    allowed_tools_json = json.dumps(body.allowed_tools) if body.allowed_tools is not None else None
    disallowed_tools_json = json.dumps(body.disallowed_tools) if body.disallowed_tools is not None else None

    execute(
        """INSERT INTO projects
           (id, organization_id, title, description, problem_statement_md,
            time_limit_minutes, difficulty, allowed_tools, disallowed_tools,
            rubric, max_budget_usd)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            project_id,
            org_id,
            body.title,
            body.description,
            body.problem_statement_md,
            body.time_limit_minutes,
            body.difficulty,
            allowed_tools_json,
            disallowed_tools_json,
            rubric_json,
            body.max_budget_usd,
        ),
    )

    row = _get_project_or_404(project_id, org_id)
    return _row_to_response(row)


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: str, current_user: CurrentUser) -> ProjectResponse:
    """Get a single project."""
    row = _get_project_or_404(project_id, current_user["organization_id"])
    return _row_to_response(row)


@router.put("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: str,
    body: ProjectUpdate,
    current_user: CurrentUser,
) -> ProjectResponse:
    """Update a project."""
    org_id = current_user["organization_id"]
    _get_project_or_404(project_id, org_id)

    updates: list[str] = []
    params: list = []

    if body.title is not None:
        updates.append("title = ?")
        params.append(body.title)
    if body.description is not None:
        updates.append("description = ?")
        params.append(body.description)
    if body.problem_statement_md is not None:
        updates.append("problem_statement_md = ?")
        params.append(body.problem_statement_md)
    if body.time_limit_minutes is not None:
        updates.append("time_limit_minutes = ?")
        params.append(body.time_limit_minutes)
    if body.difficulty is not None:
        updates.append("difficulty = ?")
        params.append(body.difficulty)
    if body.allowed_tools is not None:
        updates.append("allowed_tools = ?")
        params.append(json.dumps(body.allowed_tools))
    if body.disallowed_tools is not None:
        updates.append("disallowed_tools = ?")
        params.append(json.dumps(body.disallowed_tools))
    if body.rubric is not None:
        updates.append("rubric = ?")
        params.append(json.dumps([dim.model_dump() for dim in body.rubric]))
    if body.max_budget_usd is not None:
        updates.append("max_budget_usd = ?")
        params.append(body.max_budget_usd)

    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    updates.append("updated_at = datetime('now')")
    params.append(project_id)
    params.append(org_id)

    execute(
        f"UPDATE projects SET {', '.join(updates)} WHERE id = ? AND organization_id = ?",
        tuple(params),
    )

    row = _get_project_or_404(project_id, org_id)
    return _row_to_response(row)


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: str, current_user: CurrentUser) -> None:
    """Soft delete a project (set is_archived=1)."""
    org_id = current_user["organization_id"]
    _get_project_or_404(project_id, org_id)

    execute(
        "UPDATE projects SET is_archived = 1, updated_at = datetime('now') WHERE id = ? AND organization_id = ?",
        (project_id, org_id),
    )
    return None


@router.post("/{project_id}/duplicate", response_model=ProjectResponse, status_code=201)
def duplicate_project(project_id: str, current_user: CurrentUser) -> ProjectResponse:
    """Duplicate a project with '(Copy)' appended to the title."""
    org_id = current_user["organization_id"]
    original = _get_project_or_404(project_id, org_id)

    new_id = secrets.token_hex(16)
    new_title = f"{original['title']} (Copy)"

    execute(
        """INSERT INTO projects
           (id, organization_id, title, description, problem_statement_md,
            time_limit_minutes, difficulty, allowed_tools, disallowed_tools,
            rubric, max_budget_usd)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            new_id,
            org_id,
            new_title,
            original["description"],
            original["problem_statement_md"],
            original["time_limit_minutes"],
            original["difficulty"],
            original["allowed_tools"],
            original["disallowed_tools"],
            original["rubric"],
            original["max_budget_usd"],
        ),
    )

    row = _get_project_or_404(new_id, org_id)
    return _row_to_response(row)
