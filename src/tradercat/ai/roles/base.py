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
    identity: str  # e.g., "options_strategist"
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
    
    @staticmethod
    def enable_llm_progress_logging(
        llm,
        role_name: str,
        identity: Optional[str] = None,
        phase: Optional[str] = None,
        progress_interval: float = 1.0,
    ) -> None:
        """
        Enable real-time progress logging on an LLM provider instance.
        
        This is typically called during role initialization to configure
        the LLM provider with role context for logging.
        
        Args:
            llm: The LLM provider instance
            role_name: Name of the role (e.g., "MacroAnalyst")
            identity: Optional identity key (e.g., "macro_analyst")
            phase: Optional pipeline phase (e.g., "P2", "P3a", "P3b")
            progress_interval: Seconds between progress updates
        """
        from tradercat.config import settings
        
        llm.enable_progress_logging(
            enabled=settings.llm_progress_logging_enabled,
            progress_interval=settings.llm_progress_interval,
            role_name=role_name,
            identity=identity,
            phase=phase,
        )
