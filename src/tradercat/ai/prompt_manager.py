import os
import glob
from typing import Dict, List, Optional
from pathlib import Path

class PromptManager:
    def __init__(self, prompts_dir: str = "prompts"):
        # Automatically find the project root or use relative path
        self.prompts_dir = Path(os.getcwd()) / prompts_dir
        self._cache: Dict[str, str] = {} # Cache content to avoid re-reading disk

    def list_analysts(self) -> List[str]:
        """
        Returns a list of available analyst names (filenames without extension).
        Example: ['wyckoff-en', 'standard-en', 'buffett-zh']
        """
        if not self.prompts_dir.exists():
            return []
        
        files = glob.glob(str(self.prompts_dir / "*.txt"))
        return [Path(f).stem for f in files]

    def get_prompt_template(self, analyst_name: str) -> str:
        """
        Loads the content of a specific analyst file.
        Adjusts for missing language suffixes if needed.
        """
        # Try exact match first
        if analyst_name in self._cache:
            return self._cache[analyst_name]

        start_path = self.prompts_dir / f"{analyst_name}.txt"
        
        # Fallback: if user typed "wyckoff" but file is "wyckoff-en.txt", try finding it
        if not start_path.exists():
            candidates = glob.glob(str(self.prompts_dir / f"{analyst_name}-*.txt"))
            if candidates:
                start_path = Path(candidates[0]) # Use the first match (e.g., english)
            else:
                raise FileNotFoundError(f"Analyst '{analyst_name}' not found in {self.prompts_dir}")

        with open(start_path, 'r', encoding='utf-8') as f:
            content = f.read()
            self._cache[analyst_name] = content
            return content