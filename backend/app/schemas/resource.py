"""Pydantic schemas for the resource API (request/response).

Both resource types reference a ResourceGroup via group_id, and optionally a Site via site_id.

GROUPS DO NEST, AND IT IS LOAD-BEARING. An earlier version of this docstring claimed "no parent_id
hierarchy" while the field existed three lines below it and while
``WorkingTimeService._load_group_hierarchy`` walked the chain to INHERIT work-profile bindings: a
binding on a plant-level group applies to its departments, the group's own binding wins over its
parent's, and cycles are guarded. Three tests in ``test_profile_resolution.py`` pin exactly that.
Do not remove ``parent_id`` on the assumption that nothing reads it.

What is genuinely missing is the other end: no screen offers a parent, so the inheritance is
reachable only by calling the API directly.

SITE IS NOT THE SAME AXIS. Site and group are orthogonal — place × trade. A resource's location is
``site_id``, never an ancestor group, so "Lackierer at Ammendorf" is one group plus one site rather
than a group nested under a plant. Encoding the plant in the group tree as well would duplicate
every trade per site and leave two sources for one fact. Nesting exists for binding inheritance,
not for location. See ADR-003.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

# --- Resource Group Schemas ---


class ResourceGroupCreate(BaseModel):
    """Request schema for creating a resource group."""

    name: str = Field(..., min_length=1, max_length=255, description="Group name")
    resource_type: Literal["personal", "infrastructure"] = Field(
        ..., description="Scope: personal or infrastructure"
    )
    parent_id: UUID | None = Field(
        None,
        description=(
            "Parent group. A work-profile binding on the parent is inherited by this group "
            "unless it carries its own."
        ),
    )


class ResourceGroupUpdate(BaseModel):
    """Request schema for updating a resource group."""

    name: str | None = Field(None, min_length=1, max_length=255)
    parent_id: UUID | None = Field(None)


class ResourceGroupResponse(BaseModel):
    """Response schema for a resource group."""

    id: UUID
    name: str
    resource_type: str
    parent_id: UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Resource Schemas (unified for personal and infrastructure) ---


class ResourceCreate(BaseModel):
    """Request schema for creating a resource (personal or infrastructure)."""

    name: str = Field(..., min_length=1, max_length=255, description="Resource name")
    group_id: UUID = Field(..., description="Resource group ID")
    site_id: UUID | None = Field(
        None,
        description=(
            "Site the resource is located at. Optional: a single-plant operator needs none, and "
            "leaving it empty is not an error. It selects which site calendar's holidays apply."
        ),
    )


class ResourceUpdate(BaseModel):
    """Request schema for updating a resource."""

    name: str | None = Field(None, min_length=1, max_length=255)
    group_id: UUID | None = Field(None, description="Resource group ID")
    site_id: UUID | None = Field(None, description="Site the resource is located at")


class ResourceResponse(BaseModel):
    """Response schema for a resource (personal or infrastructure)."""

    id: UUID
    name: str
    group_id: UUID
    group_name: str = ""
    site_id: UUID | None = None
    site_name: str = ""
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Legacy aliases for backward compatibility with existing router imports ---

PersonalResourceCreate = ResourceCreate
PersonalResourceUpdate = ResourceUpdate
PersonalResourceResponse = ResourceResponse
InfrastructureResourceCreate = ResourceCreate
InfrastructureResourceUpdate = ResourceUpdate
InfrastructureResourceResponse = ResourceResponse


# --- Tree/List Representation Schema ---


class ResourceListItemResponse(BaseModel):
    """Response schema for a resource in the flat list (with conflict count)."""

    id: UUID
    name: str
    group_id: UUID
    group_name: str = ""
    site_id: UUID | None = None
    site_name: str = ""
    is_active: bool
    conflict_count: int = 0

    model_config = {"from_attributes": True}


# Legacy aliases for tree endpoints (now flat lists)
PersonalTreeNodeResponse = ResourceListItemResponse
InfrastructureTreeNodeResponse = ResourceListItemResponse


class ErasureResponse(BaseModel):
    """What an erasure removed, per table.

    Counts rather than a bare 204, because the operator answering an Art. 17 request needs something
    to file. The field names mirror the tables so the response can be read without the source open.

    ``baseline_entries`` is deliberately absent: baselines freeze projects, work packages and
    assignments, never ``personal_resources``, so a frozen payload holds a resource UUID and no name.
    After erasure that identifier resolves to nothing.
    """

    resource_id: UUID
    skills: int
    work_profiles: int
    conflict_assignments: int
    conflicts: int
    assignments: int
    absences: int
    audit_entries: int
    unlinked_accounts: int

    model_config = {"from_attributes": True}
