"""Base role interface for the 3-role AI analysis system."""
from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, Any, Optional
from dataclasses import dataclass


class RoleType(str, Enum):
    """The three roles in the analysis pipeline."""
    IDENTITY = "identity"
    ANALYSIS = "analysis"
    SUMMARY = "summary"


@dataclass
class RoleOutput:
    """Standard output from any role execution."""
    role: RoleType
    identity: str  # e.g., "wyckoff", "options_strategist"
    content: str  # The LLM-generated markdown output
    model_used: str
    metadata: Dict[str, Any]  # Extra context (symbols, run_date, etc.)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role.value,
            "identity": self.identity,
            "content": self.content,
            "model_used": self.model_used,
            "metadata": self.metadata,
        }


class AIRole(ABC):
    """Abstract base class for AI roles in the pipeline."""
    
    @property
    @abstractmethod
    def role_type(self) -> RoleType:
        """Return the type of this role."""
        ...

    @abstractmethod
    async def execute(self, **kwargs) -> RoleOutput:
        """Execute this role's function and return structured output."""
        ...
